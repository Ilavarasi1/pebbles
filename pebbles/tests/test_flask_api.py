import unittest
import datetime
import base64
import json
import uuid
import time

from pebbles.tests.base import db, BaseTestCase
from pebbles.models import (
    User, Group, GroupUserAssociation, BlueprintTemplate, Blueprint,
    ActivationToken, Instance, NamespacedKeyValue)
from pebbles.views import activations

from pebbles.tests.fixtures import primary_test_setup

ADMIN_TOKEN = None
USER_TOKEN = None
GROUP_OWNER_TOKEN = None
GROUP_OWNER_TOKEN2 = None


class FlaskApiTestCase(BaseTestCase):
    def setUp(self):
        self.methods = {
            'GET': self.client.get,
            'POST': self.client.post,
            'PUT': self.client.put,
            'PATCH': self.client.patch,
            'DELETE': self.client.delete,
        }
        db.create_all()
        primary_test_setup(self)
        # conf = BaseConfig()

    def make_request(self, method='GET', path='/', headers=None, data=None):
        assert method in self.methods

        if not headers:
            headers = {}

        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

        header_tuples = [(x, y) for x, y in headers.items()]
        return self.methods[method](path, headers=header_tuples, data=data, content_type='application/json')

    def get_auth_token(self, creds, headers=None):
        if not headers:
            headers = {}
        response = self.make_request('POST', '/api/v1/sessions',
                                     headers=headers,
                                     data=json.dumps(creds))
        token = '%s:' % response.json['token']
        return base64.b64encode(bytes(token.encode('ascii'))).decode('utf-8')

    def make_authenticated_request(self, method='GET', path='/', headers=None, data=None, creds=None,
                                   auth_token=None):
        assert creds is not None or auth_token is not None

        assert method in self.methods

        if not headers:
            headers = {}

        if not auth_token:
            auth_token = self.get_auth_token(headers, creds)

        headers.update({
            'Accept': 'application/json',
            'Authorization': 'Basic %s' % auth_token,
            'token': auth_token
        })
        return self.methods[method](path, headers=headers, data=data, content_type='application/json')

    def make_authenticated_admin_request(self, method='GET', path='/', headers=None, data=None):
        global ADMIN_TOKEN
        if not ADMIN_TOKEN:
            ADMIN_TOKEN = self.get_auth_token({'email': 'admin@example.org', 'password': 'admin'})

        self.admin_token = ADMIN_TOKEN

        return self.make_authenticated_request(method, path, headers, data,
                                               auth_token=self.admin_token)

    def make_authenticated_user_request(self, method='GET', path='/', headers=None, data=None):
        global USER_TOKEN
        if not USER_TOKEN:
            USER_TOKEN = self.get_auth_token(creds={
                'email': self.known_user_email,
                'password': self.known_user_password}
            )
        self.user_token = USER_TOKEN
        return self.make_authenticated_request(method, path, headers, data,
                                               auth_token=self.user_token)

    def make_authenticated_group_owner_request(self, method='GET', path='/', headers=None, data=None):
        global GROUP_OWNER_TOKEN
        if not GROUP_OWNER_TOKEN:
            GROUP_OWNER_TOKEN = self.get_auth_token(creds={'email': 'group_owner@example.org', 'password': 'group_owner'})
        self.group_owner_token = GROUP_OWNER_TOKEN
        return self.make_authenticated_request(method, path, headers, data,
                                               auth_token=self.group_owner_token)

    def make_authenticated_group_owner2_request(self, method='GET', path='/', headers=None, data=None):
        global GROUP_OWNER_TOKEN2
        if not GROUP_OWNER_TOKEN2:
            GROUP_OWNER_TOKEN2 = self.get_auth_token(creds={'email': 'group_owner2@example.org', 'password': 'group_owner2'})
        self.group_owner_token2 = GROUP_OWNER_TOKEN2
        return self.make_authenticated_request(method, path, headers, data,
                                               auth_token=self.group_owner_token2)

    def test_first_user(self):
        db.drop_all()
        db.create_all()
        response = self.make_request(
            'POST',
            '/api/v1/initialize',
            data=json.dumps({'email': 'admin@example.org',
                             'password': 'admin'}))
        self.assert_200(response)

    def test_deleted_user_cannot_get_token(self):
        response = self.make_request(
            method='POST',
            path='/api/v1/sessions',
            data=json.dumps({'email': 'user@example.org', 'password': 'user'}))
        self.assert_200(response)
        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/users/%s' % self.known_user_id
        )
        self.assert_200(response)
        response = self.make_request(
            method='POST',
            path='/api/v1/sessions',
            data=json.dumps({'email': 'user@example.org', 'password': 'user'}))
        self.assert_401(response)

    def test_deleted_user_cannot_use_token(self):
        response = self.make_request(
            method='POST',
            path='/api/v1/sessions',
            data=json.dumps({'email': 'user@example.org', 'password': 'user'})
        )
        self.assert_200(response)

        token = '%s:' % response.json['token']
        token_b64 = base64.b64encode(bytes(token.encode('ascii'))).decode('utf-8')

        headers = {
            'Accept': 'application/json',
            'Authorization': 'Basic %s' % token_b64,
            'token': token_b64
        }
        # Test instance creation still works for the user
        response = self.make_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps({'blueprint': self.known_blueprint_id}),
            headers=headers)
        self.assert_200(response)
        # Delete the user with admin credentials
        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/users/%s' % self.known_user_id
        )
        self.assert_200(response)
        # Test instance creation fails for the user
        response = self.make_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps({'blueprint': self.known_blueprint_id}),
            headers=headers)
        self.assert_401(response)

    def test_delete_user(self):
        email = "test@example.org"
        u = User(email, "testuser", is_admin=False)
        # Anonymous
        db.session.add(u)
        db.session.commit()

        response = self.make_request(
            method='DELETE',
            path='/api/v1/users/%s' % u.id
        )
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(
            method='DELETE',
            path='/api/v1/users/%s' % u.id
        )
        self.assert_403(response)
        # Admin
        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/users/%s' % u.id
        )
        self.assert_200(response)
        user = User.query.filter_by(id=u.id).first()
        self.assertTrue(user.email != email)

    def test_make_group_owner(self):
        email = "test_owner@example.org"
        u = User(email, "testuser", is_admin=False)
        db.session.add(u)
        db.session.commit()
        # Anonymous
        response = self.make_request(
            method='PUT',
            path='/api/v1/users/%s/user_group_owner' % u.id,
            data=json.dumps({'make_group_owner': True})
        )
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/users/%s/user_group_owner' % u.id,
            data=json.dumps({'make_group_owner': True})
        )
        self.assert_403(response)
        # Group Owner
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/users/%s/user_group_owner' % u.id,
            data=json.dumps({'make_group_owner': True})
        )
        self.assert_403(response)
        # Admin
        # Make Group Owner
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/users/%s/user_group_owner' % u.id,
            data=json.dumps({'make_group_owner': True})
        )
        self.assert_200(response)
        user = User.query.filter_by(id=u.id).first()
        self.assertTrue(user.is_group_owner)
        # Remove Group Owner
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/users/%s/user_group_owner' % u.id,
            data=json.dumps({'make_group_owner': False})
        )
        self.assert_200(response)
        user = User.query.filter_by(id=u.id).first()
        self.assertFalse(user.is_group_owner)

    def test_block_user(self):
        email = "test@example.org"
        u = User(email, "testuser", is_admin=False)
        db.session.add(u)
        db.session.commit()
        # Anonymous
        response = self.make_request(
            method='PUT',
            path='/api/v1/users/%s/user_blacklist' % u.id,
            data=json.dumps({'block': True})
        )
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/users/%s/user_blacklist' % u.id,
            data=json.dumps({'block': True})
        )
        self.assert_403(response)
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/users/%s/user_blacklist' % u.id,
            data=json.dumps({'block': True})
        )
        self.assert_403(response)
        # Admin
        # Block
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/users/%s/user_blacklist' % u.id,
            data=json.dumps({'block': True})
        )
        self.assert_200(response)
        user = User.query.filter_by(id=u.id).first()
        self.assertTrue(user.is_blocked)
        # Unblock
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/users/%s/user_blacklist' % u.id,
            data=json.dumps({'block': False})
        )
        self.assert_200(response)
        user = User.query.filter_by(id=u.id).first()
        self.assertFalse(user.is_blocked)

    def test_get_users(self):
        # Anonymous
        response = self.make_request(path='/api/v1/users')
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/users')
        self.assertEqual(len(response.json), 1)
        self.assert_200(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/users')
        self.assert_200(response)

    def test_get_groups(self):
        # Anonymous
        response = self.make_request(path='/api/v1/groups')
        self.assert_401(response)
        # Authenticated User
        response = self.make_authenticated_user_request(path='/api/v1/groups')
        self.assert_403(response)
        # Authenticated Group Owner
        response = self.make_authenticated_group_owner_request(path='/api/v1/groups')
        self.assert_200(response)
        self.assertEqual(len(response.json), 1)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/groups')
        self.assert_200(response)
        self.assertEqual(len(response.json), 5)
        # Get One
        response = self.make_authenticated_admin_request(path='/api/v1/groups/%s' % self.known_group_id)
        self.assert_200(response)

    def test_create_group(self):

        data = {
            'name': 'TestGroup',
            'description': 'Group Details',
            'user_config': {
                'users': [{'id': self.known_user_id}],
                'banned_users': [],
                'owners': []
            }
        }
        data_2 = {
            'name': 'TestGroup2',
            'description': 'Group Details',
            'user_config': {
                'banned_users': [{'id': self.known_user_id}],
            }
        }
        data_3 = {
            'name': 'TestGroup',
            'description': 'Group Details',
            'user_config': {
            }
        }
        # Anonymous
        response = self.make_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(data))
        self.assertStatus(response, 401)
        # Authenticated User
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(data))
        self.assertStatus(response, 403)
        # Group Owner
        response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(data))
        self.assertStatus(response, 200)

        response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(data_2))
        self.assertStatus(response, 200)

        response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(data_3))
        self.assertStatus(response, 200)
        # Admin
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(data))
        self.assertStatus(response, 200)

    def test_create_group_invalid_data(self):
        invalid_data = {
            'name': '',
            'description': 'Group Details',
        }
        # Try to create system level groups
        invalid_system_data = {
            'name': 'System.Group',
            'description': 'Group Details',
            'user_config': {
            }
        }
        invalid_system_data_2 = {
            'name': 'system group',
            'description': 'Group Details',
            'user_config': {
            }
        }
        invalid_response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(invalid_data))
        self.assertStatus(invalid_response, 422)

        invalid_response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(invalid_system_data))
        self.assertStatus(invalid_response, 422)

        invalid_response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/groups',
            data=json.dumps(invalid_system_data_2))
        self.assertStatus(invalid_response, 422)

    def test_modify_group(self):

        g = Group('TestGroupModify')
        # g.owner_id = self.known_group_owner_id
        u1 = User.query.filter_by(id=self.known_user_id).first()
        gu1_obj = GroupUserAssociation(user=u1, group=g)
        u2 = User.query.filter_by(id=self.known_group_owner_id_2).first()
        gu2_obj = GroupUserAssociation(user=u2, group=g)
        u3 = User.query.filter_by(id=self.known_group_owner_id).first()
        gu3_obj = GroupUserAssociation(user=u3, group=g, manager=True, owner=True)
        g.users.append(gu1_obj)
        g.users.append(gu2_obj)
        g.users.append(gu3_obj)
        db.session.add(g)
        db.session.commit()

        data_ban = {
            'name': 'TestGroupModify',
            'description': 'Group Details',
            'user_config': {
                'banned_users': [{'id': u1.id}]
            }
        }
        data_manager = {
            'name': 'TestGroupModify',
            'description': 'Group Details',
            'user_config': {
                'managers': [{'id': u2.id}]
            }
        }
        response_ban = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/%s' % g.id,
            data=json.dumps(data_ban))
        self.assertStatus(response_ban, 200)

        response_manager = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/%s' % g.id,
            data=json.dumps(data_manager))
        self.assertStatus(response_manager, 200)

    def test_modify_group_invalid_data(self):

        invalid_data = {
            'name': 'TestGroup bogus id',
            'description': 'Group Details',
            'user_config': {
                'banned_users': [{'id': 'bogusx10'}]
            }
        }
        invalid_data_1 = {
            'name': 'TestGroup manager cannot be banned',
            'description': 'Group Details',
            'user_config': {
                'banned_users': [{'id': self.known_user_id}],
                'managers': [{'id': self.known_user_id}]
            }
        }
        invalid_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/%s' % self.known_group_id,
            data=json.dumps(invalid_data))
        self.assertStatus(invalid_response, 422)

        invalid_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/%s' % self.known_group_id,
            data=json.dumps(invalid_data_1))
        self.assertStatus(invalid_response, 422)

    def test_delete_group(self):
        name = 'GroupToBeDeleted'
        g = Group(name)
        g.owner_id = self.known_group_owner_id
        db.session.add(g)
        db.session.commit()
        # Anonymous
        response = self.make_request(
            method='DELETE',
            path='/api/v1/groups/%s' % g.id
        )
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(
            method='DELETE',
            path='/api/v1/groups/%s' % g.id
        )
        self.assert_403(response)
        # Authenticated
        response = self.make_authenticated_group_owner_request(
            method='DELETE',
            path='/api/v1/groups/%s' % g.id
        )
        self.assert_403(response)
        # Admin
        invalid_response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/groups/%s' % self.system_default_group_id
        )
        self.assertStatus(invalid_response, 422)  # Cannot delete default system group
        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/groups/%s' % g.id
        )
        self.assert_200(response)
        group = Group.query.filter_by(id=g.id).first()
        self.assertIsNone(group)

    def test_join_group(self):
        # Anonymous
        response = self.make_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % self.known_group_join_id)
        self.assertStatus(response, 401)
        # Authenticated User
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % self.known_group_join_id)
        self.assertStatus(response, 200)
        # Group Owner
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % self.known_group_join_id)
        self.assertStatus(response, 200)

    def test_join_group_invalid(self):
        g = Group('InvalidTestGroup')
        g.owner_id = self.known_group_owner_id
        u = User.query.filter_by(id=self.known_user_id).first()
        gu_obj = GroupUserAssociation()
        gu_obj.user = u
        gu_obj.group = g

        g.users.append(gu_obj)
        db.session.add(g)
        db.session.commit()
        # Authenticated User
        invalid_response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_join/')
        self.assertStatus(invalid_response, 405)  # Not allowed without joining code
        # Authenticated User Bogus Code
        invalid_response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % 'bogusx10')
        self.assertStatus(invalid_response, 422)
        # Group Owner Bogus Code
        invalid_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % 'bogusx10')
        self.assertStatus(invalid_response, 422)
        # Authenticated User - Trying to Join the same group again
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % g.join_code)
        self.assertStatus(response, 422)

    def test_join_group_banned_user(self):

        # Authenticated User
        banned_response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % self.known_banned_group_join_id)
        self.assertStatus(banned_response, 403)

        # Authenticated Group Owner
        banned_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/group_join/%s' % self.known_banned_group_join_id)
        self.assertStatus(banned_response, 403)

    def test_group_exit_list(self):
        # Anonymous
        response = self.make_request(path='/api/v1/groups/group_list_exit')
        self.assert_401(response)
        # Authenticated User
        response = self.make_authenticated_user_request(path='/api/v1/groups/group_list_exit')
        self.assert_200(response)
        self.assertEqual(len(response.json), 1)
        # Authenticated Group Owner
        response = self.make_authenticated_group_owner_request(path='/api/v1/groups/group_list_exit')
        self.assert_200(response)
        self.assertEqual(len(response.json), 1)  # Only the groups where the owner is a normal user
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/groups/group_list_exit')
        self.assert_200(response)
        self.assertEqual(len(response.json), 0)

    def test_exit_group(self):
        g = Group('TestGroupExit')
        g.owner_id = self.known_group_owner_id_2
        u = User.query.filter_by(id=self.known_user_id).first()
        gu_obj = GroupUserAssociation(group=g, user=u)

        u_extra = User.query.filter_by(id=self.known_group_owner_id).first()  # extra user
        gu_extra_obj = GroupUserAssociation(group=g, user=u_extra)

        g.users.append(gu_obj)
        g.users.append(gu_extra_obj)

        db.session.add(g)
        db.session.commit()
        # Anonymous
        response = self.make_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % g.id)
        self.assertStatus(response, 401)
        # Authenticated User of the group
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % g.id)
        self.assertStatus(response, 200)
        # self.assertEqual(len(g.users.all()), 1)
        # Group Owner who is just a user of the group
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % g.id)
        self.assertStatus(response, 200)
        # self.assertEqual(len(g.users.all()), 0)

    def test_exit_group_invalid(self):
        g = Group('InvalidTestGroupExit')
        u = User.query.filter_by(id=self.known_group_owner_id).first()
        gu_obj = GroupUserAssociation(group=g, user=u, manager=True, owner=True)
        g.users.append(gu_obj)
        db.session.add(g)
        db.session.commit()
        # Authenticated User
        invalid_response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_exit/')
        self.assertStatus(invalid_response, 405)  # Not allowed without group id
        # Authenticated User Bogus group id
        invalid_response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % 'bogusx10')
        self.assertStatus(invalid_response, 404)
        # Group Owner Bogus group id
        invalid_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % 'bogusx10')
        self.assertStatus(invalid_response, 404)
        # Authenticated User - Trying to exit a group without
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % g.id)
        self.assertStatus(response, 403)
        # Group Owner of the group
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/groups/group_exit/%s' % g.id)
        self.assertStatus(response, 422)  # owner of the group cannot exit the group

    def test_get_group_users(self):

        # Authenticated User, not a manager
        response = self.make_authenticated_user_request(
            method='GET',
            path='/api/v1/groups/%s/users' % self.known_group_id)
        self.assertStatus(response, 403)

        # Authenticated Group Owner , who does not own the group
        response = self.make_authenticated_group_owner_request(
            method='GET',
            path='/api/v1/groups/%s/users' % self.known_group_id_2,
            data=json.dumps({})
        )
        self.assertStatus(response, 403)

        # Authenticated Group Owner , is a Manager too
        response = self.make_authenticated_group_owner_request(
            method='GET',
            path='/api/v1/groups/%s/users' % self.known_group_id,
            data=json.dumps({})
        )
        self.assertStatus(response, 200)
        self.assertEqual(len(response.json), 2)  # 1 normal user + 1 manager (1 group owner not taken into account)

        # Authenticated Group Owner , is a Manager too
        response = self.make_authenticated_admin_request(
            method='GET',
            path='/api/v1/groups/%s/users' % self.known_group_id,
            data=json.dumps({})
        )
        self.assertStatus(response, 200)
        self.assertEqual(len(response.json), 2)  # 1 normal user + 1 manager (1 group owner not taken into account)

        # Authenticated Group Owner , is a Manager too
        response = self.make_authenticated_group_owner_request(
            method='GET',
            path='/api/v1/groups/%s/users' % self.known_group_id,
            data=json.dumps({'banned_list': True})
        )
        self.assertStatus(response, 200)
        self.assertEqual(len(response.json), 1)  # 1 normal user

    def test_get_plugins(self):
        # Anonymous
        response = self.make_request(path='/api/v1/plugins')
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/plugins')
        self.assert_403(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/plugins')
        self.assert_200(response)

    def test_get_single_plugin(self):
        # Anonymous
        response = self.make_request(path='/api/v1/plugins/%s' % self.known_plugin_id)
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/plugins/%s' % self.known_plugin_id)
        self.assert_403(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/plugins/%s' % self.known_plugin_id)
        self.assert_200(response)

        response = self.make_authenticated_admin_request(path='/api/v1/plugins/%s' % 'doesnotexists')
        self.assert_404(response)

    def test_admin_create_plugin(self):
        data = {
            'plugin': 'TestPlugin',
            'schema': json.dumps({}),
            'form': json.dumps({}),
            'model': json.dumps({})
        }
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/plugins',
            data=json.dumps(data))
        self.assert_200(response)

        data = {
            'plugin': 'TestPluginNew',
            'schema': json.dumps({}),
            'form': json.dumps({}),
            'model': json.dumps({})
        }
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/plugins',
            data=json.dumps(data))
        self.assert_200(response)

        data = {
            'plugin': 'TestPlugin',
            'schema': None,
            'form': json.dumps({}),
            'model': json.dumps({})
        }
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/plugins',
            data=json.dumps(data))
        self.assertStatus(response, 422)

    def test_get_blueprint_templates(self):
        # Anonymous
        response = self.make_request(path='/api/v1/blueprint_templates')
        self.assert_401(response)
        # Authenticated User
        response = self.make_authenticated_user_request(path='/api/v1/blueprint_templates')
        self.assert_403(response)
        # Authenticated Group Owner
        response = self.make_authenticated_group_owner_request(path='/api/v1/blueprint_templates')
        self.assert_200(response)
        self.assertEqual(len(response.json), 1)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/blueprint_templates')
        self.assert_200(response)
        self.assertEqual(len(response.json), 2)

    def test_get_blueprint_template(self):
        # Existing blueprint
        # Anonymous
        response = self.make_request(path='/api/v1/blueprint_templates/%s' % self.known_blueprint_id)
        self.assert_401(response)
        # Authenticated User
        response = self.make_authenticated_user_request(path='/api/v1/blueprint_templates/%s' % self.known_template_id)
        self.assert_403(response)
        # Group Owner
        response = self.make_authenticated_group_owner_request(path='/api/v1/blueprint_templates/%s' % self.known_template_id)
        self.assert_200(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/blueprint_templates/%s' % self.known_template_id)
        self.assert_200(response)

        # non-existing blueprint
        # Anonymous
        response = self.make_request(path='/api/v1/blueprint_templates/%s' % uuid.uuid4().hex)
        self.assert_401(response)
        # Authenticated User
        response = self.make_authenticated_user_request(path='/api/v1/blueprint_templates/%s' % uuid.uuid4().hex)
        self.assert_403(response)
        # Group Owner
        response = self.make_authenticated_group_owner_request(path='/api/v1/blueprint_templates/%s' % uuid.uuid4().hex)
        self.assert_404(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/blueprint_templates/%s' % uuid.uuid4().hex)
        self.assert_404(response)

    def test_create_blueprint_template(self):
        # Anonymous
        data = {'name': 'test_blueprint_template_1', 'config': '', 'plugin': 'dummy'}
        response = self.make_request(
            method='POST',
            path='/api/v1/blueprint_templates',
            data=json.dumps(data))
        self.assert_401(response)
        # Authenticated User
        data = {'name': 'test_blueprint_template_1', 'config': '', 'plugin': 'dummy'}
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/blueprint_templates',
            data=json.dumps(data))
        self.assert_403(response)
        # Authenticated Group Owner
        data = {'name': 'test_blueprint_template_1', 'config': '', 'plugin': 'dummy'}
        response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/blueprint_templates',
            data=json.dumps(data))
        self.assert_403(response)
        # Admin
        data = {'name': 'test_blueprint_template_1', 'config': {'foo': 'bar'}, 'plugin': 'dummy'}
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/blueprint_templates',
            data=json.dumps(data))
        self.assert_200(response)
        # Admin
        data = {
            'name': 'test_blueprint_template_2',
            'config': {'foo': 'bar', 'maximum_lifetime': '1h'},
            'allowed_attrs': {'allowed_attrs': ['maximum_lifetime']},
            'plugin': self.known_plugin_id
        }
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/blueprint_templates',
            data=json.dumps(data))
        self.assert_200(response)

    def test_modify_blueprint_template(self):
        t = BlueprintTemplate()
        t.name = 'TestTemplate'
        t.plugin = self.known_plugin_id
        t.config = {'memory_limit': '512m', 'maximum_lifetime': '1h'}
        t.allowed_attrs = ['maximum_lifetime']
        t.is_enabled = True
        db.session.add(t)
        db.session.commit()

        # Anonymous
        data = {'name': 'test_blueprint_template_1', 'config': '', 'plugin': 'dummy'}
        response = self.make_request(
            method='PUT',
            path='/api/v1/blueprint_templates/%s' % t.id,
            data=json.dumps(data))
        self.assert_401(response)
        # Authenticated User
        data = {'name': 'test_blueprint_template_1', 'config': '', 'plugin': 'dummy'}
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/blueprint_templates/%s' % t.id,
            data=json.dumps(data))
        self.assert_403(response)
        # Authenticated Group Owner
        data = {'name': 'test_blueprint_template_1', 'config': '', 'plugin': 'dummy'}
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/blueprint_templates/%s' % t.id,
            data=json.dumps(data))
        self.assert_403(response)
        # Admin
        data = {'name': 'test_blueprint_template_1', 'config': {'foo': 'bar'}, 'plugin': 'dummy'}
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/blueprint_templates/%s' % t.id,
            data=json.dumps(data))
        self.assert_200(response)
        # Admin
        data = {
            'name': 'test_blueprint_template_2',
            'config': {'foo': 'bar', 'maximum_lifetime': '1h'},
            'allowed_attrs': {'allowed_attrs': ['maximum_lifetime']},
            'plugin': self.known_plugin_id
        }
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/blueprint_templates/%s' % t.id,
            data=json.dumps(data))
        self.assert_200(response)

    def test_copy_blueprint_template(self):

        # Authenticated User
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/blueprint_templates/template_copy/%s' % self.known_template_id)
        self.assert_403(response)
        # Authenticated Group Owner
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/blueprint_templates/template_copy/%s' % self.known_template_id)
        self.assert_403(response)
        # Admin
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/blueprint_templates/template_copy/%s' % self.known_template_id)
        self.assert_200(response)

    def test_get_blueprints(self):
        # Anonymous
        response = self.make_request(path='/api/v1/blueprints')
        self.assert_401(response)
        # Authenticated User for Group 1
        response = self.make_authenticated_user_request(path='/api/v1/blueprints')
        self.assert_200(response)
        self.assertEqual(len(response.json), 2)
        # Authenticated Group Owner for Group 1 and Normal User for Group 2
        response = self.make_authenticated_group_owner_request(path='/api/v1/blueprints')
        self.assert_200(response)
        self.assertEqual(len(response.json), 4)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/blueprints')
        self.assert_200(response)
        self.assertEqual(len(response.json), 5)

    def test_get_blueprint(self):
        # Existing blueprint
        # Anonymous
        response = self.make_request(path='/api/v1/blueprints/%s' % self.known_blueprint_id)
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/blueprints/%s' % self.known_blueprint_id)
        self.assert_200(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/blueprints/%s' % self.known_blueprint_id)
        self.assert_200(response)

        # non-existing blueprint
        # Anonymous
        response = self.make_request(path='/api/v1/blueprints/%s' % uuid.uuid4().hex)
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/blueprints/%s' % uuid.uuid4().hex)
        self.assert_404(response)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/blueprints/%s' % uuid.uuid4().hex)
        self.assert_404(response)

    def test_create_blueprint(self):
        # Anonymous
        data = {'name': 'test_blueprint_1', 'config': '', 'template_id': self.known_template_id, 'group_id': self.known_group_id}
        response = self.make_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(data))
        self.assert_401(response)
        # Authenticated
        data = {'name': 'test_blueprint_1', 'config': '', 'template_id': self.known_template_id, 'group_id': self.known_group_id}
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(data))
        self.assert_403(response)
        # Group Owner 1
        data = {'name': 'test_blueprint_1', 'config': {'foo': 'bar'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id}
        response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(data))
        self.assert_200(response)
        # Group Owner 2 (extra owner added to group 1)
        response = self.make_authenticated_group_owner2_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(data))
        self.assert_200(response)
        # Admin
        data = {'name': 'test_blueprint_1', 'config': {'foo': 'bar'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id}
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(data))
        self.assert_200(response)

    def test_create_blueprint_full_config(self):
        # Group Owner
        data = {
            'name': 'test_blueprint_2',
            'config': {
                'foo': 'bar',
                'memory_limit': '1024m',
                'maximum_lifetime': '10h'
            },
            'template_id': self.known_template_id,
            'group_id': self.known_group_id
        }
        post_response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(data))
        self.assert_200(post_response)

        blueprint = Blueprint.query.filter_by(name='test_blueprint_2').first()
        blueprint_id = blueprint.id

        get_response = self.make_authenticated_group_owner_request(
            method='GET',
            path='/api/v1/blueprints/%s' % blueprint_id)
        self.assert_200(get_response)
        blueprint_json = get_response.json
        self.assertNotIn('foo', blueprint_json['full_config'])  # 'foo' exists in blueprint config but not in template config
        self.assertNotEqual(blueprint_json['full_config']['memory_limit'], '1024m')  # blueprint config value (memory_limit is not an allowed attribute)
        self.assertEquals(blueprint_json['full_config']['memory_limit'], '512m')  # blueprint template value (memory_limit is not an allowed attribute)
        self.assertEquals(blueprint_json['full_config']['maximum_lifetime'], '10h')  # blueprint config value overrides template value (allowed attribute)

    def test_create_modify_blueprint_timeformat(self):

        form_data = [
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1d 1h 40m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1d1h40m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1d'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '10h'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '30m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '5h30m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1d12h'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1d 10m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1h 1m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '0d2h 30m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": ''}, 'template_id': self.known_template_id, 'group_id': self.known_group_id}
        ]
        expected_lifetimes = [92400, 92400, 86400, 36000, 1800, 19800, 129600, 87000, 3660, 9000, 3600]

        self.assertEquals(len(form_data), len(expected_lifetimes))

        for data, expected_lifetime in zip(form_data, expected_lifetimes):
            response = self.make_authenticated_admin_request(
                method='POST',
                path='/api/v1/blueprints',
                data=json.dumps(data))
            self.assert_200(response,
                            'testing time %s,%d failed' % (data['config']['maximum_lifetime'], expected_lifetime))

            put_response = self.make_authenticated_admin_request(
                method='PUT',
                path='/api/v1/blueprints/%s' % self.known_blueprint_id_2,
                data=json.dumps(data))
            self.assert_200(put_response)

            blueprint = Blueprint.query.filter_by(id=self.known_blueprint_id_2).first()
            self.assertEqual(blueprint.maximum_lifetime, expected_lifetime)

    def test_modify_blueprint_activate(self):
        data = {
            'name': 'test_blueprint_activate',
            'config': {
                "maximum_lifetime": "0h"
            },
            'template_id': self.known_template_id,
            'group_id': self.known_group_id
        }

        # Authenticated Normal User
        put_response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_disabled,
            data=json.dumps(data))
        self.assert_403(put_response)
        # Group owner not an owner of the blueprint group 2
        put_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_disabled_2,
            data=json.dumps(data))
        self.assert_403(put_response)
        # Group Owner is an owner of the blueprint group 1
        put_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_disabled,
            data=json.dumps(data))
        self.assert_200(put_response)
        # Group owner 2 is part of the blueprint group 1 as an additional owner
        put_response = self.make_authenticated_group_owner2_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_disabled,
            data=json.dumps(data))
        self.assert_200(put_response)
        # Group owner 2 owner of the blueprint group 2
        put_response = self.make_authenticated_group_owner2_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_disabled,
            data=json.dumps(data))
        self.assert_200(put_response)
        # Admin
        put_response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_disabled,
            data=json.dumps(data))
        self.assert_200(put_response)

        blueprint = Blueprint.query.filter_by(id=self.known_blueprint_id_disabled).first()
        self.assertEqual(blueprint.is_enabled, False)

    def test_modify_blueprint_config_magic_vars_admin(self):
        data = {
            'name': 'test_blueprint_2',
            'config': {
                "name": "foo_modify",
                "maximum_lifetime": '0d2h30m',
                "cost_multiplier": '0.1',
                "preallocated_credits": "true",
            },
            'template_id': self.known_template_id,
            'group_id': self.known_group_id
        }
        put_response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_2,
            data=json.dumps(data))
        self.assert_200(put_response)

        blueprint = Blueprint.query.filter_by(id=self.known_blueprint_id_2).first()
        self.assertEqual(blueprint.maximum_lifetime, 9000)
        self.assertEqual(blueprint.cost_multiplier, 0.1)
        self.assertEqual(blueprint.preallocated_credits, True)

    def test_create_blueprint_admin_invalid_data(self):
        invalid_form_data = [
            {'name': '', 'config': 'foo: bar', 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': '', 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': 'foo: bar', 'template_id': self.known_template_id},
            {'name': 'test_blueprint_2', 'config': 'foo: bar', 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": ' '}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '10 100'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '1hh'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '-1m'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '-10h'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '2d -10h'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '30s'}, 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '10h'}, 'template_id': self.known_template_id, 'group_id': 'unknown'},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '10h'}, 'template_id': 'unknown', 'group_id': self.known_group_id},
        ]
        for data in invalid_form_data:
            response = self.make_authenticated_admin_request(
                method='POST',
                path='/api/v1/blueprints',
                data=json.dumps(data))
            self.assertStatus(response, 422)

    def test_create_blueprint_template_admin_invalid_data(self):
        invalid_form_data = [
            {'name': '', 'config': 'foo: bar'},
            {'name': 'test_template_2', 'config': ''},
            {'name': 'test_template_2', 'config': 'foo: bar'},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": ' '}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '10 100'}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '1hh'}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '-1m'}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '-10h'}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '2d -10h'}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '30s'}},
            {'name': 'test_template_2', 'config': {"name": "foo", "maximum_lifetime": '10h'}}
        ]
        for data in invalid_form_data:
            response = self.make_authenticated_admin_request(
                method='POST',
                path='/api/v1/blueprint_templates',
                data=json.dumps(data))
            self.assertStatus(response, 422)

    def test_create_blueprint_group_owner_invalid_data(self):
        invalid_form_data = [
            {'name': '', 'config': 'foo: bar', 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': '', 'template_id': self.known_template_id, 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': 'foo: bar', 'template_id': self.known_template_id},
            {'name': 'test_blueprint_2', 'config': 'foo: bar', 'group_id': self.known_group_id},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '10h'}, 'template_id': self.known_template_id, 'group_id': 'unknown'},
            {'name': 'test_blueprint_2', 'config': {"name": "foo", "maximum_lifetime": '10h'}, 'template_id': 'unknown', 'group_id': self.known_group_id},
        ]
        for data in invalid_form_data:
            response = self.make_authenticated_group_owner_request(
                method='POST',
                path='/api/v1/blueprints',
                data=json.dumps(data))
            self.assertStatus(response, 422)

        # Group owner is a user but not the owner of the group with id : known_group_id_2
        invalid_group_data = {'name': 'test_blueprint_2', 'config': {"name": "foo"}, 'template_id': self.known_template_id, 'group_id': self.known_group_id_2}
        response = self.make_authenticated_group_owner_request(
            method='POST',
            path='/api/v1/blueprints',
            data=json.dumps(invalid_group_data))
        self.assertStatus(response, 403)

        put_response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/blueprints/%s' % self.known_blueprint_id_g2,
            data=json.dumps(invalid_group_data))
        self.assertStatus(put_response, 403)

    def test_copy_blueprints(self):

        # Authenticated User
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/blueprints/blueprint_copy/%s' % self.known_blueprint_id)
        self.assert_403(response)
        # Authenticated Group Owner
        response = self.make_authenticated_group_owner_request(
            method='PUT',
            path='/api/v1/blueprints/blueprint_copy/%s' % self.known_blueprint_id)
        self.assert_200(response)
        # Admin
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/blueprints/blueprint_copy/%s' % self.known_blueprint_id)
        self.assert_200(response)

    def test_anonymous_invite_user(self):
        data = {'email': 'test@example.org', 'password': 'test', 'is_admin': True}
        response = self.make_request(
            method='POST',
            path='/api/v1/users',
            data=json.dumps(data))
        self.assert_401(response)

    def test_user_invite_user(self):
        data = {'email': 'test@example.org', 'password': 'test', 'is_admin': True}
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/users',
            data=json.dumps(data))
        self.assert_403(response)

    def test_admin_invite_user(self):
        data = {'email': 'test@example.org', 'is_admin': True}
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/users',
            data=json.dumps(data))
        self.assert_200(response)
        user = User.query.filter_by(email='test@example.org').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_admin)

        data = {'email': 'test2@example.org', 'is_admin': False}
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/users',
            data=json.dumps(data))
        self.assert_200(response)
        user = User.query.filter_by(email='test2@example.org').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_admin)

    def test_admin_delete_invited_user_deletes_activation_tokens(self):
        data = {'email': 'test@example.org'}
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/users',
            data=json.dumps(data))
        self.assert_200(response)
        user = User.query.filter_by(email='test@example.org').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_active)
        self.assertEqual(ActivationToken.query.filter_by(user_id=user.id).count(), 1)
        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/users/%s' % user.id
        )
        self.assert_200(response)
        self.assertEqual(ActivationToken.query.filter_by(user_id=user.id).count(), 0)

    def test_accept_invite(self):
        user = User.query.filter_by(email='test@example.org').first()
        self.assertIsNone(user)
        data = {'email': 'test@example.org', 'password': None, 'is_admin': True}
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/users',
            data=json.dumps(data))
        self.assert_200(response)
        user = User.query.filter_by(email='test@example.org').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_active)
        token = ActivationToken.query.filter_by(user_id=user.id).first()
        self.assertIsNotNone(token)
        data = {'password': 'testtest'}
        response = self.make_request(
            method='POST',
            path='/api/v1/activations/%s' % token.token,
            data=json.dumps(data))
        self.assert_200(response)
        user = User.query.filter_by(email='test@example.org').first()
        default_group = Group.query.filter_by(name='System.default').first()
        self.assertIsNotNone(user)
        self.assertTrue(user.is_active)

        user_in_group = GroupUserAssociation.query.filter_by(group_id=default_group.id, user_id=user.id).first()
        self.assertIsNotNone(user_in_group)  # Each active user gets added in the system default group

    def test_send_recovery_link(self):
        # positive test for existing user
        user = User.query.filter_by(id=self.known_user_id).first()
        self.assertIsNotNone(user)
        data = {'email': user.email}
        response = self.make_request(
            method='POST',
            path='/api/v1/activations',
            data=json.dumps(data))
        self.assert_200(response)

        # negative test for existing user with too many tokens
        for i in range(1, activations.MAX_ACTIVATION_TOKENS_PER_USER):
            response = self.make_request(
                method='POST',
                path='/api/v1/activations',
                data=json.dumps(data))
            self.assert_200(response)
        response = self.make_request(
            method='POST',
            path='/api/v1/activations',
            data=json.dumps(data))
        self.assert_403(response)

        # negative test for non-existing user
        user = User.query.filter_by(email='not.here@example.org').first()
        self.assertIsNone(user)
        data = {'email': 'not.here@example.org'}
        response = self.make_request(
            method='POST',
            path='/api/v1/activations',
            data=json.dumps(data))
        self.assert_404(response)

    def test_anonymous_create_instance(self):
        data = {'blueprint_id': self.known_blueprint_id}
        response = self.make_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps(data))
        self.assert_401(response)

    def test_user_create_instance(self):
        # User is not a part of the group (Group2)
        data = {'blueprint': self.known_blueprint_id_g2}
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps(data))
        self.assert_403(response)
        # User is a part of the group (Group1)
        data = {'blueprint': self.known_blueprint_id}
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps(data))
        self.assert_200(response)

    def test_user_create_instance_blueprint_disabled(self):
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps({'blueprint': self.known_blueprint_id_disabled}),
        )
        self.assert_404(response)

    def test_anonymous_update_client_ip(self):
        data = {'client_ip': '1.1.1.1'}
        response = self.make_request(
            method='PATCH',
            path='/api/v1/instances/%s' % self.known_instance_id_2,
            data=json.dumps(data))
        self.assert_401(response)

    def test_update_client_ip(self):
        # first test with an instance from a blueprint that does not allow setting client ip
        data = {'client_ip': '1.1.1.1'}
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/instances/%s' % self.known_instance_id,
            data=json.dumps(data))
        self.assert_400(response)

        # then a positive test case
        data = {'client_ip': '1.1.1.1'}
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/instances/%s' % self.known_instance_id_2,
            data=json.dumps(data))
        self.assert_200(response)

        # test illegal ips
        for ip in ['1.0.0.0.0', '256.0.0.1', 'a.1.1.1', '10.10.10.']:
            data = {'client_ip': ip}
            response = self.make_authenticated_user_request(
                method='PUT',
                path='/api/v1/instances/%s' % self.known_instance_id_2,
                data=json.dumps(data))
            self.assertStatus(response, 422)

    def test_get_instances(self):
        # Anonymous
        response = self.make_request(path='/api/v1/instances')
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/instances')
        self.assert_200(response)
        self.assertEqual(len(response.json), 2)
        response = self.make_authenticated_user_request(path='/api/v1/instances?show_deleted=true')
        self.assert_200(response)
        self.assertEqual(len(response.json), 3)
        # Group Manager (His own instance + other instances from his managed groups)
        response = self.make_authenticated_group_owner_request(path='/api/v1/instances')
        self.assert_200(response)
        self.assertEqual(len(response.json), 3)
        # Admin
        response = self.make_authenticated_admin_request(path='/api/v1/instances')
        self.assert_200(response)
        self.assertEqual(len(response.json), 4)
        response = self.make_authenticated_admin_request(path='/api/v1/instances?show_only_mine=1')
        self.assert_200(response)
        self.assertEqual(len(response.json), 1)

    def test_get_instance(self):
        # Anonymous
        response = self.make_request(path='/api/v1/instances/%s' % self.known_instance_id)
        self.assert_401(response)
        # Authenticated
        response = self.make_authenticated_user_request(
            method='GET',
            path='/api/v1/instances/%s' % self.known_instance_id,
            data=json.dumps({'check_provisioning': False})
        )
        self.assert_200(response)
        # Admin
        response = self.make_authenticated_admin_request(
            method='GET',
            path='/api/v1/instances/%s' % self.known_instance_id,
            data=json.dumps({'check_provisioning': False})
        )
        self.assert_200(response)

    def test_delete_instance(self):
        blueprint = Blueprint.query.filter_by(id=self.known_blueprint_id).first()
        user = User.query.filter_by(id=self.known_user_id).first()
        i1 = Instance(blueprint, user)
        db.session.add(i1)
        db.session.commit()
        # Anonymous
        response = self.make_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i1.id
        )
        self.assert_401(response)
        # Authenticated User of the instance
        response = self.make_authenticated_user_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i1.id
        )
        self.assert_200(response)

        i2 = Instance(blueprint, user)
        db.session.add(i2)
        db.session.commit()
        # Authenticated Group Owner of the instance
        response = self.make_authenticated_group_owner_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i2.id
        )
        self.assert_200(response)

        i3 = Instance(blueprint, user)
        db.session.add(i3)
        db.session.commit()
        # Authenticated Group Manager of the instance
        response = self.make_authenticated_group_owner2_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i3.id
        )
        self.assert_200(response)

        i4 = Instance(blueprint, user)
        db.session.add(i4)
        db.session.commit()
        # Admin
        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i4.id
        )
        self.assert_200(response)

        blueprint2 = Blueprint.query.filter_by(id=self.known_blueprint_id_g2).first()
        user2 = User.query.filter_by(id=self.known_group_owner_id_2).first()
        i5 = Instance(blueprint2, user2)
        db.session.add(i5)
        db.session.commit()
        # User is not part of the group
        response = self.make_authenticated_user_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i5.id
        )
        self.assert_404(response)
        # Is just a Normal user of the group who didn't spawn the instance
        response = self.make_authenticated_group_owner_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i5.id
        )
        self.assert_403(response)
        # Authenticated Group Owner of the group
        response = self.make_authenticated_group_owner2_request(
            method='DELETE',
            path='/api/v1/instances/%s' % i5.id
        )
        self.assert_200(response)

    def test_instance_logs(self):
        epoch_time = time.time()
        log_record = {
            'log_level': 'INFO',
            'log_type': 'provisioning',
            'timestamp': epoch_time,
            'message': 'log testing'
        }
        response_patch = self.make_authenticated_admin_request(
            method='PATCH',
            path='/api/v1/instances/%s/logs' % self.known_instance_id,
            data=json.dumps({'log_record': log_record})
        )
        self.assert_200(response_patch)

        response_get = self.make_authenticated_user_request(
            method='GET',
            path='/api/v1/instances/%s/logs' % self.known_instance_id,
            data=json.dumps({'log_type': 'provisioning'})
        )
        self.assert_200(response_get)
        self.assertEquals(response_get.json[0]['timestamp'], epoch_time)

        response_instance_get = self.make_authenticated_user_request(
            method='GET',
            path='/api/v1/instances/%s' % self.known_instance_id,
            data=json.dumps({'check_provisioning': False})
        )
        self.assert_200(response_instance_get)
        self.assertEquals(response_instance_get.json['logs'][0]['timestamp'], epoch_time)

    def test_get_activation_url(self):

        t1 = ActivationToken(User.query.filter_by(id=self.known_user_id).first())
        known_token = t1.token
        db.session.add(t1)

        # Anonymous
        response = self.make_request(path='/api/v1/users/%s/user_activation_url' % self.known_user_id)
        self.assert_401(response)
        response2 = self.make_request(path='/api/v1/users/%s/user_activation_url' % '0xBogus')
        self.assert_401(response2)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/users/%s/user_activation_url' % self.known_user_id)
        self.assert_403(response)
        response2 = self.make_authenticated_user_request(path='/api/v1/users/%s/user_activation_url' % '0xBogus')
        self.assert_403(response2)
        # Admin
        response = self.make_authenticated_admin_request(
            path='/api/v1/users/%s/user_activation_url' % self.known_user_id
        )
        self.assert_200(response)
        token_check = known_token in response.json['activation_url']
        self.assertTrue(token_check)
        response2 = self.make_authenticated_admin_request(path='/api/v1/users/%s/activation_url' % '0xBogus')
        self.assert_404(response2)

    def test_get_keypairs(self):
        # Anonymous
        response = self.make_request(path='/api/v1/users/%s/keypairs' % self.known_user_id)
        self.assert_401(response)
        response2 = self.make_request(path='/api/v1/users/%s/keypairs' % '0xBogus')
        self.assert_401(response2)
        # Authenticated
        response = self.make_authenticated_user_request(path='/api/v1/users/%s/keypairs' % self.known_user_id)
        self.assert_200(response)
        self.assertEqual(len(response.json), 0)
        response2 = self.make_authenticated_user_request(path='/api/v1/users/%s/keypairs' % '0xBogus')
        self.assert_403(response2)
        # Admin
        response = self.make_authenticated_admin_request(
            path='/api/v1/users/%s/keypairs' % self.known_user_id
        )
        self.assert_200(response)
        self.assertEqual(len(response.json), 0)
        response2 = self.make_authenticated_admin_request(path='/api/v1/users/%s/keypairs' % '0xBogus')
        self.assert_404(response2)

    def test_user_over_quota_cannot_launch_instances(self):
        data = {'blueprint': self.known_blueprint_id}
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps(data)).json
        instance = Instance.query.filter_by(id=response['id']).first()
        instance.provisioned_at = datetime.datetime(2015, 1, 1, 0, 0, 0)
        instance.deprovisioned_at = datetime.datetime(2015, 1, 1, 1, 0, 0)

        db.session.commit()
        response2 = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/instances',
            data=json.dumps(data))
        self.assertEqual(response2.status_code, 409)

    def test_update_admin_quota_relative(self):
        response = self.make_authenticated_admin_request(
            path='/api/v1/users'
        )
        assert abs(response.json[0]['credits_quota'] - 1) < 0.001
        user_id = response.json[0]['id']
        response2 = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/quota/%s' % user_id,
            data=json.dumps({'type': 'relative', 'value': 10}))
        self.assertEqual(response2.status_code, 200)
        response = self.make_authenticated_admin_request(
            path='/api/v1/users'
        )
        self.assertEqual(user_id, response.json[0]['id'])
        assert abs(response.json[0]['credits_quota'] - 11) < 0.001

    def test_update_quota_absolute(self):
        response = self.make_authenticated_admin_request(
            path='/api/v1/users'
        )

        for user in response.json:
            assert abs(user['credits_quota'] - 1) < 0.001

        response2 = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/quota',
            data=json.dumps({'type': 'absolute', 'value': 42}))
        self.assertEqual(response2.status_code, 200)

        response3 = self.make_authenticated_admin_request(
            path='/api/v1/users'
        )

        for user in response3.json:
            assert abs(user['credits_quota'] - 42) < 0.001

    def test_user_cannot_update_user_quota_absolute(self):
        response = self.make_authenticated_user_request(
            path='/api/v1/users'
        )
        self.assertEqual(len(response.json), 1)
        user_id = response.json[0]['id']
        response2 = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/quota/%s' % user_id,
            data=json.dumps({'type': "absolute", 'value': 10}))
        self.assert_403(response2)

    def test_user_cannot_update_quotas(self):
        response = self.make_authenticated_user_request(
            method='PUT',
            path='/api/v1/quota',
            data=json.dumps({'type': "absolute", 'value': 10}))
        self.assert_403(response)

    def test_anonymous_cannot_see_quota_list(self):
        response = self.make_request(
            path='/api/v1/quota'
        )
        self.assert_401(response)

    def test_user_cannot_see_quota_list(self):
        response = self.make_authenticated_user_request(
            path='/api/v1/quota'
        )
        self.assert_403(response)

    def test_admin_get_quota_list(self):
        response = self.make_authenticated_admin_request(
            path='/api/v1/quota'
        )
        self.assert_200(response)

    def test_anonymous_cannot_see_user_quota(self):
        response2 = self.make_request(
            path='/api/v1/quota/%s' % self.known_user_id
        )
        self.assert_401(response2)

    def test_user_get_own_quota(self):
        response = self.make_authenticated_user_request(
            path='/api/v1/quota/%s' % self.known_user_id
        )
        self.assert_200(response)

    def test_parse_invalid_quota_update(self):
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/quota',
            data=json.dumps({'type': "invalid_type", 'value': 10}))
        self.assertStatus(response, 422)
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/quota',
            data=json.dumps({'type': "relative", 'value': "foof"}))
        self.assertStatus(response, 422)

    def test_user_cannot_see_other_users(self):
        response = self.make_authenticated_user_request(
            path='/api/v1/quota/%s' % self.known_admin_id
        )
        self.assert_403(response)

    def test_anonymous_what_is_my_ip(self):
        response = self.make_request(path='/api/v1/what_is_my_ip')
        self.assert_401(response)

    def test_what_is_my_ip(self):
        response = self.make_authenticated_user_request(path='/api/v1/what_is_my_ip')
        self.assert_200(response)

    def test_admin_acquire_lock(self):
        unique_id = 'abc123'
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/locks/%s' % unique_id)
        self.assertStatus(response, 200)

        response2 = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/locks/%s' % unique_id)
        self.assertStatus(response2, 409)

        response3 = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/locks/%s' % unique_id)
        self.assertStatus(response3, 200)

        response4 = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/locks/%s' % unique_id)
        self.assertStatus(response4, 404)

        unique_id = 'abc123'
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/locks/%s' % unique_id)
        self.assertStatus(response, 200)

    def test_user_and_group_owner_export_blueprint_templates(self):
        response = self.make_authenticated_user_request(path='/api/v1/import_export/blueprint_templates')
        self.assertStatus(response, 403)

        response = self.make_authenticated_group_owner_request(path='/api/v1/import_export/blueprint_templates')
        self.assertStatus(response, 403)

    def test_admin_export_blueprint_templates(self):

        response = self.make_authenticated_admin_request(path='/api/v1/import_export/blueprint_templates')
        self.assertStatus(response, 200)
        self.assertEquals(len(response.json), 2)  # There were total 2 templates initialized during setup

    def test_user_and_group_owner_import_blueprint_templates(self):

        blueprints_data = [
            {'name': 'foo',
             'config': {
                 'maximum_lifetime': '1h'
             },
             'plugin_name': 'TestPlugin',
             'allowed_attrs': ['maximum_lifetime']
             },
            {'name': 'foobar',
             'config': {
                 'maximum_lifetime': '1d 10m', 'description': 'dummy blueprint'
             },
             'plugin_name': 'TestPlugin',
             'allowed_attrs': []
             }
        ]
        # Authenticated User
        for blueprint_item in blueprints_data:
            response = self.make_authenticated_user_request(
                method='POST',
                path='/api/v1/import_export/blueprint_templates',
                data=json.dumps(blueprint_item))
            self.assertEqual(response.status_code, 403)
        # Group Owner
        for blueprint_item in blueprints_data:
            response = self.make_authenticated_group_owner_request(
                method='POST',
                path='/api/v1/import_export/blueprint_templates',
                data=json.dumps(blueprint_item))
            self.assertEqual(response.status_code, 403)

    def test_admin_import_blueprint_templates(self):

        blueprints_data = [
            {'name': 'foo',
             'config': {
                 'maximum_lifetime': '1h'
             },
             'plugin_name': 'TestPlugin',
             'allowed_attrs': ['maximum_lifetime']
             },
            {'name': 'foobar',
             'config': {
                 'maximum_lifetime': '1d 10m', 'description': 'dummy blueprint'
             },
             'plugin_name': 'TestPlugin',
             'allowed_attrs': []
             }
        ]
        # Admin
        for blueprint_item in blueprints_data:
            response = self.make_authenticated_admin_request(
                method='POST',
                path='/api/v1/import_export/blueprint_templates',
                data=json.dumps(blueprint_item))
            self.assertEqual(response.status_code, 200)

    def test_anonymous_export_blueprints(self):
        response = self.make_request(path='/api/v1/import_export/blueprints')
        self.assertStatus(response, 401)

    def test_user_export_blueprints(self):
        response = self.make_authenticated_user_request(path='/api/v1/import_export/blueprints')
        self.assertStatus(response, 403)

    def test_group_owner_export_blueprints(self):
        response = self.make_authenticated_group_owner_request(path='/api/v1/import_export/blueprints')
        self.assertStatus(response, 200)
        self.assertEquals(len(response.json), 3)

    def test_admin_export_blueprints(self):

        response = self.make_authenticated_admin_request(path='/api/v1/import_export/blueprints')
        self.assertStatus(response, 200)
        self.assertEquals(len(response.json), 5)  # There were total 5 blueprints initialized during setup

    def test_anonymous_import_blueprints(self):

        blueprints_data = [
            {'name': 'foo',
             'config': {
                 'maximum_lifetime': '1h'
             },
             'template_name': 'TestTemplate',
             'group_name': 'Group1'
             },
            {'name': 'foobar',
             'config': {
                 'maximum_lifetime': '1d 10m', 'description': 'dummy blueprint'
             },
             'template_name': 'TestTemplate',
             'group_name': 'Group1'
             }
        ]

        for blueprint_item in blueprints_data:
            response = self.make_request(  # Test for authenticated user
                method='POST',
                path='/api/v1/import_export/blueprints',
                data=json.dumps(blueprint_item))
            self.assertEqual(response.status_code, 401)

    def test_user_import_blueprints(self):

        blueprints_data = [
            {'name': 'foo',
             'config': {
                 'maximum_lifetime': '1h'
             },
             'template_name': 'TestTemplate',
             'group_name': 'Group1'
             },
            {'name': 'foobar',
             'config': {
                 'maximum_lifetime': '1d 10m', 'description': 'dummy blueprint'
             },
             'template_name': 'TestTemplate',
             'group_name': 'Group1'
             }
        ]

        for blueprint_item in blueprints_data:
            response = self.make_authenticated_user_request(  # Test for authenticated user
                method='POST',
                path='/api/v1/import_export/blueprints',
                data=json.dumps(blueprint_item))
            self.assertEqual(response.status_code, 403)

    def test_admin_import_blueprints(self):

        blueprints_data = [
            {'name': 'foo',
             'config': {
                 'maximum_lifetime': '1h'
             },
             'template_name': 'EnabledTestTemplate',
             'group_name': 'Group1'
             },
            {'name': 'foobar',
             'config': {
                 'maximum_lifetime': '1d 10m', 'description': 'dummy blueprint'
             },
             'template_name': 'EnabledTestTemplate',
             'group_name': 'Group1'
             }
        ]

        for blueprint_item in blueprints_data:
            response = self.make_authenticated_admin_request(
                method='POST',
                path='/api/v1/import_export/blueprints',
                data=json.dumps(blueprint_item))
            self.assertEqual(response.status_code, 200)

        blueprint_invalid1 = {'name': 'foo', 'template_name': 'EnabledTestTemplate', 'group_name': 'Group1'}
        response1 = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/import_export/blueprints',
            data=json.dumps(blueprint_invalid1))
        self.assertEqual(response1.status_code, 422)

        blueprint_invalid2 = {'name': '', 'template_name': 'EnabledTestTemplate', 'group_name': 'Group1'}
        response2 = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/import_export/blueprints',
            data=json.dumps(blueprint_invalid2))
        self.assertEqual(response2.status_code, 422)

        blueprint_invalid3 = {'name': 'foo', 'config': {'maximum_lifetime': '1h'}, 'template_name': '', 'group_name': 'Group1'}
        response3 = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/import_export/blueprints',
            data=json.dumps(blueprint_invalid3))
        self.assertEqual(response3.status_code, 422)

        blueprint_invalid4 = {'name': 'foo', 'config': {'maximum_lifetime': '1h'}, 'template_name': 'EnabledTestTemplate', 'group_name': ''}
        response3 = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/import_export/blueprints',
            data=json.dumps(blueprint_invalid4))
        self.assertEqual(response3.status_code, 422)

    def test_anonymous_get_notifications(self):
        response = self.make_request(
            path='/api/v1/notifications'
        )
        self.assert_401(response)

    def test_user_get_notifications(self):
        response = self.make_authenticated_user_request(
            path='/api/v1/notifications'
        )
        self.assert_200(response)
        self.assertEqual(len(response.json), 2)

    def test_anonymous_post_notification(self):
        response = self.make_request(
            method='POST',
            path='/api/v1/notifications',
            data=json.dumps({'subject': 'test subject', 'message': 'test message'})
        )
        self.assert_401(response)

    def test_user_post_notification(self):
        response = self.make_authenticated_user_request(
            method='POST',
            path='/api/v1/notifications',
            data=json.dumps({'subject': 'test subject', 'message': 'test message'})
        )
        self.assert_403(response)

    def test_admin_post_notification(self):
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/notifications',
            data=json.dumps({'subject': 'test subject', 'message': 'test message'})
        )
        self.assert_200(response)
        response = self.make_authenticated_user_request(
            path='/api/v1/notifications'
        )
        self.assert_200(response)
        self.assertEqual(len(response.json), 3)

    def test_user_mark_notification_as_seen(self):
        response = self.make_authenticated_user_request(
            method='PATCH',
            path='/api/v1/notifications/%s' % self.known_notification_id,
            data=json.dumps({'send_mail': False})
        )
        self.assert_200(response)

        response = self.make_authenticated_user_request(
            path='/api/v1/notifications'
        )
        self.assert_200(response)
        self.assertEqual(len(response.json), 1)

        response = self.make_authenticated_user_request(
            method='PATCH',
            path='/api/v1/notifications/%s' % self.known_notification2_id,
            data=json.dumps({'send_mail': False})
        )
        self.assert_200(response)

        response = self.make_authenticated_user_request(
            path='/api/v1/notifications'
        )
        self.assert_200(response)
        self.assertEqual(len(response.json), 0)

    def test_admin_update_notification(self):
        subject_topic = 'NotificationABC'
        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/notifications/%s' % self.known_notification_id,
            data=json.dumps({'subject': subject_topic, 'message': 'XXX'}))
        self.assert_200(response)

        response = self.make_authenticated_admin_request(
            path='/api/v1/notifications/%s' % self.known_notification_id)
        self.assert_200(response)
        self.assertEqual(response.json['subject'], subject_topic)

    def test_admin_fetch_instance_usage_stats(self):
        response = self.make_authenticated_admin_request(
            method='GET',
            path='/api/v1/stats')
        self.assertStatus(response, 200)

        self.assertEqual(len(response.json['blueprints']), 3)  # 2 items as the instances are running across three blueprints
        for blueprint in response.json['blueprints']:
            # Tests for blueprint b2 EnabledTestBlueprint'
            if blueprint['name'] == 'EnabledTestBlueprint':
                self.assertEqual(blueprint['users'], 1)
                self.assertEqual(blueprint['launched_instances'], 1)
                self.assertEqual(blueprint['running_instances'], 1)
            # Tests for blueprint b3 EnabledTestBlueprintClientIp
            elif blueprint['name'] == 'EnabledTestBlueprintClientIp':
                self.assertEqual(blueprint['users'], 2)
                self.assertEqual(blueprint['launched_instances'], 3)
                self.assertEqual(blueprint['running_instances'], 2)
            # b4 EnabledTestBlueprintOtherGroup
            else:
                self.assertEqual(blueprint['users'], 1)
                self.assertEqual(blueprint['launched_instances'], 1)
                self.assertEqual(blueprint['running_instances'], 1)

        self.assertEqual(response.json['overall_running_instances'], 4)

    def test_user_fetch_instance_usage_stats(self):
        response = self.make_authenticated_user_request(
            method='GET',
            path='/api/v1/stats')
        self.assertStatus(response, 403)

    def test_create_namespaced_data(self):
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': 'MockDriver', 'key': 'test_pool_vm_0', 'value': json.dumps({"attr": "val"})})
        )
        self.assert_200(response)

        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': 'TestDriver', 'key': 'test_pool_vm_1', 'value': json.dumps({"attr": "val"})})
        )
        self.assert_200(response)

        get_response = self.make_authenticated_admin_request(
            method='GET',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({})
        )
        self.assert_200(get_response)
        self.assertEqual(len(get_response.json), 2)

        get_response = self.make_authenticated_admin_request(
            method='GET',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': 'TestDriver'})
        )
        self.assert_200(get_response)
        self.assertEqual(len(get_response.json), 1)

    def test_create_duplicate_namespaced_data(self):
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': 'TestDriver', 'key': 'test_pool_vm_2', 'value': json.dumps({"attr": "val"})})
        )
        self.assert_200(response)

        # The combination of namespace and key has to be unique
        response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': 'TestDriver', 'key': 'test_pool_vm_2', 'value': json.dumps({"attr": "new_val"})})
        )
        self.assertStatus(response, 422)

    def test_update_namespaced_data(self):
        ns = "TestDriver"
        key = "pool_vm_test_3"
        ns_kv = NamespacedKeyValue(ns, key)
        ns_kv.value = {'attr': 'val'}
        ts = 1000000000
        ns_kv.created_ts = ts
        ns_kv.updated_ts = ts
        db.session.add(ns_kv)
        db.session.commit()

        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (ns, key),
            data=json.dumps({'namespace': ns, 'key': key, 'value': json.dumps({"attr": "NEW_VAL"}), 'updated_version_ts': ts})
        )
        self.assert_200(response)

    def test_invalid_create_update_namespaced_data(self):
        invalid_response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': 'TestDriver', 'key': 0, 'value': {"attr": "val"}})
        )
        self.assertStatus(invalid_response, 422)

        invalid_response = self.make_authenticated_admin_request(
            method='POST',
            path='/api/v1/namespaced_keyvalues',
            data=json.dumps({'namespace': '', 'key': 'test_pool_vm_4', 'value': {"attr": "val"}})
        )
        self.assertStatus(invalid_response, 422)

        ns = "TestDriver"
        key = "pool_vm_test_4"
        ns_kv = NamespacedKeyValue(ns, key)
        ns_kv.value = {'attr': 'val'}
        ts = 1000000000
        ns_kv.created_ts = ts
        ns_kv.updated_ts = ts
        db.session.add(ns_kv)
        db.session.commit()
        # Invalid update time
        invalid_response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (ns, key),
            data=json.dumps({'namespace': ns, 'key': key, 'value': json.dumps({"attr": "val"}), 'updated_version_ts': 'bogusx10'})
        )
        self.assertStatus(invalid_response, 422)
        # namespace and key cannot change
        invalid_response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (ns, key),
            data=json.dumps({'namespace': ns, 'key': 'bogus_key', 'value': json.dumps({"attr": "val"}), 'updated_version_ts': ts})
        )
        self.assertStatus(invalid_response, 422)

        invalid_response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (ns, key),
            data=json.dumps({'namespace': 'Bogus', 'key': 'bogus_key', 'value': json.dumps({"attr": "val"}), 'updated_version_ts': ts})
        )
        self.assertStatus(invalid_response, 422)

    def test_concurrent_update_namespaced_data(self):
        namespace = "TestDriver"
        key = "test_pool_vm_5"
        namespace_keyvalue_obj = NamespacedKeyValue(namespace, key)
        namespace_keyvalue_obj.value = {'attribute': 'value'}
        ts = 1000000000
        namespace_keyvalue_obj.created_ts = ts
        namespace_keyvalue_obj.updated_ts = ts
        db.session.add(namespace_keyvalue_obj)
        db.session.commit()

        response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (namespace, key),
            data=json.dumps({'namespace': namespace, 'key': key, 'value': json.dumps({"attr": "val"}), 'updated_version_ts': ts})
        )
        self.assert_200(response)

        # Concurrent Modification
        invalid_response = self.make_authenticated_admin_request(
            method='PUT',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (namespace, key),
            data=json.dumps({'namespace': namespace, 'key': key, 'value': json.dumps({"another_attr": "another_val"}), 'updated_version_ts': ts})
        )
        self.assertStatus(invalid_response, 409)

    def test_delete_namespaced_data(self):
        namespace = "TestDriver"
        key = "test_pool_vm_6"
        namespace_keyvalue_obj = NamespacedKeyValue(namespace, key)
        namespace_keyvalue_obj.value = {'attribute': 'value'}
        ts = 1000000000
        namespace_keyvalue_obj.created_ts = ts
        namespace_keyvalue_obj.updated_ts = ts
        db.session.add(namespace_keyvalue_obj)
        db.session.commit()

        response = self.make_authenticated_admin_request(
            method='DELETE',
            path='/api/v1/namespaced_keyvalues/%s/%s' % (namespace, key)
        )
        self.assert_200(response)

        invalid_response = self.make_authenticated_admin_request(
            method='GET',
            path='/api/v1/namespaced_keyvalues/%s/%s' % ('TestDriver', 'test_pool_vm_6')
        )
        self.assertStatus(invalid_response, 404)


if __name__ == '__main__':
    unittest.main()
