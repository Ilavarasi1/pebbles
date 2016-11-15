from pouta_blueprints.models import Blueprint, BlueprintTemplate, Instance
from pouta_blueprints.utils import is_group_manager
from sqlalchemy import or_, and_
from sqlalchemy.orm import load_only
from sqlalchemy.sql.expression import true
import itertools
# import logging


def apply_rules_blueprint_templates(user, args=None):

    q = BlueprintTemplate.query
    if not user.is_admin:
        query_exp = BlueprintTemplate.is_enabled == true()
        q = q.filter(query_exp)
    if args is not None and 'template_id' in args:
        q = q.filter_by(id=args.get('template_id'))

    return q


def apply_rules_blueprints(user, args=None):

    q = Blueprint.query
    if not user.is_admin:
        group_ids = [group_item.id for group_item in user.groups]
        banned_group_ids = [banned_group_item.id for banned_group_item in user.banned_groups]
        managed_group_ids = [managed_group_item.id for managed_group_item in user.managed_groups]
        allowed_group_ids = set(group_ids) - set(banned_group_ids)  # do not allow the banned users

        # Start building query expressions based on the condition that :
        # a group manager can see all of his blueprints and only enabled ones of other groups
        query_exp = Blueprint.is_enabled == true()
        allowed_group_ids_exp = None
        if allowed_group_ids:
            allowed_group_ids_exp = Blueprint.group_id.in_(allowed_group_ids)
        query_exp = and_(allowed_group_ids_exp, query_exp)
        managed_group_ids_exp = None
        if managed_group_ids:
            managed_group_ids_exp = Blueprint.group_id.in_(managed_group_ids)
        query_exp = or_(query_exp, managed_group_ids_exp)
        q = q.filter(query_exp)

    if args is not None and 'blueprint_id' in args:
        q = q.filter_by(id=args.get('blueprint_id'))

    return q


def apply_rules_export_blueprints(user):
    q = Blueprint.query
    if not user.is_admin:
        managed_group_ids = [managed_group_item.id for managed_group_item in user.managed_groups]
        query_exp = None
        if managed_group_ids:
            query_exp = Blueprint.group_id.in_(managed_group_ids)
        q = q.filter(query_exp)
    return q


def get_group_blueprint_ids_for_instances(groups):

    # loading only id column rest will be deferred
    group_blueprints = [group_item.blueprints.options(load_only("id")).all() for group_item in groups]
    group_blueprints_flat = list(itertools.chain.from_iterable(group_blueprints))  # merge the list of lists into one list
    group_blueprints_id = [blueprint_item.id for blueprint_item in group_blueprints_flat]  # Get the ids in a list
    return group_blueprints_id


def apply_rules_instances(user, args=None):

    q = Instance.query
    if not user.is_admin:
        q1 = q.filter_by(user_id=user.id)
        if is_group_manager(user):  # Show only the instances of the blueprints which the group manager holds
            groups = user.managed_groups
            group_blueprints_id = get_group_blueprint_ids_for_instances(groups)
            q2 = q.filter(Instance.blueprint_id.in_(group_blueprints_id))
            q = q1.union(q2)
        else:
            q = q1
    if args is None or not args.get('show_deleted'):
        q = q.filter(Instance.state != Instance.STATE_DELETED)
    if args is not None:
        if 'instance_id' in args:
            q = q.filter_by(id=args.get('instance_id'))
        if args.get('show_only_mine'):
            q = q.filter_by(user_id=user.id)
        if 'offset' in args:
            q = q.offset(args.get('offset'))
        if 'limit' in args:
            q = q.limit(args.get('limit'))
    return q
