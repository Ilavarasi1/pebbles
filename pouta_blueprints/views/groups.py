from flask.ext.restful import marshal_with, reqparse
from flask import abort, g
from flask import Blueprint as FlaskBlueprint
import logging
from pouta_blueprints.models import db, Group, User
from pouta_blueprints.forms import GroupForm
from pouta_blueprints.server import restful
from pouta_blueprints.views.commons import auth, group_fields, user_fields
from pouta_blueprints.utils import requires_admin, requires_group_owner_or_admin, requires_group_manager_or_admin
import re

groups = FlaskBlueprint('groups', __name__)


class GroupList(restful.Resource):
    @auth.login_required
    @requires_group_manager_or_admin
    @marshal_with(group_fields)
    def get(self):
        user = g.user
        results = []
        if not user.is_admin:
            groups = user.managed_groups
        else:
            query = Group.query
            groups = query.all()

        for group in groups:
            if user.is_admin or (group.owner_id == user.id):
                group.config = {"name": group.name, "join_code": group.join_code, "description": group.description}
                group.user_config = generate_user_config(group)
            else:
                group.config = {}
                group.user_config = {}
            results.append(group)
        return results

    @auth.login_required
    @requires_group_owner_or_admin
    def post(self):
        form = GroupForm()
        if not form.validate_on_submit():
            logging.warn("validation error on creating group")
            return form.errors, 422
        group = Group(form.name.data)
        group.description = form.description.data
        group.owner_id = g.user.id
        user_config = {'banned_users': [], 'managers': []}
        try:
            group = group_users_add(group, user_config)
        except KeyError:
            abort(422)
        db.session.add(group)
        db.session.commit()


class GroupView(restful.Resource):
    @auth.login_required
    @requires_admin
    @marshal_with(group_fields)
    def get(self, group_id):

        query = Group.query.filter_by(id=group_id)
        group = query.first()
        if not group:
            abort(404)
        return group

    @auth.login_required
    @requires_group_owner_or_admin
    def put(self, group_id):
        form = GroupForm()
        if not form.validate_on_submit():
            logging.warn("validation error on creating group")
            return form.errors, 422
        user = g.user
        group = Group.query.filter_by(id=group_id).first()
        if not group:
            abort(404)
        if not user.is_admin and group not in user.owned_groups:
            abort(403)
        if group.name != form.name.data:
            group.name = form.name.data
            group.join_code = form.name.data  # hybrid property
        group.description = form.description.data

        user_config = form.user_config.data
        try:
            group = group_users_add(group, user_config)
        except KeyError:
            abort(422)
        except RuntimeError as e:
            return {"error": "{}".format(e)}, 422

        db.session.add(group)
        db.session.commit()

    @auth.login_required
    @requires_admin
    def delete(self, group_id):
        group = Group.query.filter_by(id=group_id).first()
        if group.name == 'System.default':
            logging.warn("cannot delete the default system group")
            return {"error": "Cannot delete the default system group"}, 422
        if not group:
            logging.warn("trying to delete non-existing group")
            abort(404)
        db.session.delete(group)
        db.session.commit()


def group_users_add(group, user_config):
    # Add Banned users
    banned_users_final = []
    if 'banned_users' in user_config:
        banned_users = user_config['banned_users']
        for banned_user_item in banned_users:
            banned_user_id = banned_user_item['id']
            banned_user = User.query.filter_by(id=banned_user_id).first()
            if not banned_user:
                logging.warn("user %s does not exist", banned_user_id)
                raise RuntimeError('User to be banned, does not exist')
            banned_users_final.append(banned_user)
    group.banned_users = banned_users_final  # setting a new list adds and also removes relationships
    # Add Group Managers
    managers_final = []
    managers_final.append(g.user)  # Always add the user creating/modifying the group
    if 'managers' in user_config:
        managers = user_config['managers']
        for manager_item in managers:
            manager_id = manager_item['id']
            manager = User.query.filter_by(id=manager_id).first()
            if not manager:
                logging.warn("trying to add non-existent manager %s", manager_id)
                raise RuntimeError('User to be added as manager not found')
            if manager in banned_users_final:  # Check if the user is not banned
                logging.warn("user %s is banned, cannot add as a manager", manager_id)
                raise RuntimeError('Cannot ban a manager')
            managers_final.append(manager)
    group.managers = managers_final
    # Check status of users
    users_final = []
    if group.users:
        for user in group.users:
            if user in banned_users_final:
                logging.warn('user %s is banned, cannot add', user.id)
                continue
            if user in managers_final:
                logging.warn('user %s is a manager, not adding as normal user', user.id)
                continue
            users_final.append(user)
    group.users = users_final

    return group


def generate_user_config(group):

    user_config = {'banned_users': [], 'managers': []}
    if group.banned_users:
        for banned_user in group.banned_users:
            user_config['banned_users'].append({'id': banned_user.id})
    if group.managers:
        for manager in group.managers:
            if manager.id != group.owner_id:
                user_config['managers'].append({'id': manager.id})
    return user_config


class GroupJoin(restful.Resource):
    @auth.login_required
    def put(self, join_code):
        user = g.user
        group = Group.query.filter_by(join_code=join_code).first()
        if not group:
            logging.warn("invalid group join code %s", join_code)
            return {"error": "The code entered is invalid. Please recheck and try again"}, 422
        if user in group.banned_users:
            logging.warn("user banned from the group with code %s", join_code)
            return {"error": "You are banned from this group, please contact the concerned person"}, 403
        if user in group.users:
            logging.warn("user %s already exists in group", user.id)
            return {"error": "User already in the group"}, 422
        group.users.append(user)
        db.session.add(group)
        db.session.commit()


class GroupListExit(restful.Resource):
    @auth.login_required
    @marshal_with(group_fields)
    def get(self):
        user = g.user
        results = []
        groups = user.groups + user.managed_groups
        for group in groups:
            if re.match('^System.+', group.name):  # Do not show system level groups
                continue
            group.config = {}
            group.user_config = {}
            results.append(group)
        return results


class GroupExit(restful.Resource):
    @auth.login_required
    def put(self, group_id):
        user = g.user
        group = Group.query.filter_by(id=group_id).first()
        if not group:
            logging.warn("no group with id %s", group_id)
            abort(404)
        if user.id == group.owner_id:
            logging.warn("cannot exit the owned group %s", group_id)
            return {"error": "Cannot exit the group which is owned by you"}, 422
        if user not in group.users and user not in group.managers:
            logging.warn("user %s is not a part of the group", user.id)
            abort(403)
        if user in group.users:
            group.users.remove(user)
        elif user in group.managers:
            group.managers.remove(user)
        db.session.add(group)
        db.session.commit()


class GroupUsersList(restful.Resource):
    parser = reqparse.RequestParser()
    parser.add_argument('banned_list', type=bool)

    @auth.login_required
    @requires_group_owner_or_admin
    @marshal_with(user_fields)
    def get(self, group_id):
        args = self.parser.parse_args()
        banned_list = args.banned_list
        user = g.user
        owned_groups = user.owned_groups.all()
        group = Group.query.filter_by(id=group_id).first()
        if not group:
            logging.warn('group %s does not exist', group_id)
            abort(404)
        if not user.is_admin and group not in owned_groups:
            logging.warn('Group %s not owned, cannot see users', group_id)
            abort(403)
        users = group.users.all()
        total_users = None
        if banned_list:
            banned_users = group.banned_users.all()
            total_users = users + banned_users
        else:
            managers = group.managers.filter(User.id != group.owner_id).all()
            total_users = users + managers
        return total_users
