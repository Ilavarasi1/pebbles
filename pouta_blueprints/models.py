import random
from flask.ext.bcrypt import Bcrypt
import names
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.ext.hybrid import hybrid_property, Comparator
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.schema import MetaData
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
import logging
import uuid
import json
import datetime
import six

from pouta_blueprints.utils import validate_ssh_pubkey


MAX_PASSWORD_LENGTH = 100
MAX_EMAIL_LENGTH = 128
MAX_NAME_LENGTH = 128
MAX_VARIABLE_KEY_LENGTH = 512
MAX_VARIABLE_VALUE_LENGTH = 512
MAX_NOTIFICATION_SUBJECT_LENGTH = 255

db = SQLAlchemy()

bcrypt = Bcrypt()

NAME_ADJECTIVES = (
    'happy',
    'sad',
    'bright',
    'dark',
    'blue',
    'yellow',
    'red',
    'green',
    'white',
    'black',
    'clever',
    'witty',
    'smiley',
)

metadata = MetaData(naming_convention={
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
})


class CaseInsensitiveComparator(Comparator):
    def __eq__(self, other):
        return func.lower(self.__clause_element__()) == func.lower(other)


def load_column(column):
    try:
        value = json.loads(column)
    except:
        value = {}
    return value


class User(db.Model):
    __tablename__ = 'users'
    metadata = metadata

    id = db.Column(db.String(32), primary_key=True)
    _email = db.Column('email', db.String(MAX_EMAIL_LENGTH), unique=True)
    password = db.Column(db.String(MAX_PASSWORD_LENGTH))
    is_admin = db.Column(db.Boolean, default=False)
    is_group_owner = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    is_blocked = db.Column(db.Boolean, default=False)
    credits_quota = db.Column(db.Float, default=1.0)
    latest_seen_notification_ts = db.Column(db.DateTime)
    instances = db.relationship('Instance', backref='user', lazy='dynamic')
    activation_tokens = db.relationship('ActivationToken', backref='user', lazy='dynamic')

    def __init__(self, email, password=None, is_admin=False):
        self.id = uuid.uuid4().hex
        self.email = email
        self.is_admin = is_admin
        if password:
            self.set_password(password)
            self.is_active = True
        else:
            self.set_password(uuid.uuid4().hex)

    def __eq__(self, other):
        return self.id == other.id

    @hybrid_property
    def email(self):
        return self._email.lower()

    @email.setter
    def email(self, value):
        self._email = value.lower()

    @email.comparator
    def email(cls):
        return CaseInsensitiveComparator(cls._email)

    def delete(self):
        if self.is_deleted:
            return
        self.email = self.email + datetime.datetime.utcnow().strftime("-%s")
        self.activation_tokens.delete()
        self.is_deleted = True
        self.is_active = False

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password)

    def check_password(self, password):
        if self.can_login():
            return bcrypt.check_password_hash(self.password, password)

    def generate_auth_token(self, app_secret, expires_in=3600):
        s = Serializer(app_secret, expires_in=expires_in)
        return s.dumps({'id': self.id}).decode('utf-8')

    def calculate_credits_spent(self):
        return sum(instance.credits_spent() for instance in self.instances.all())

    def quota_exceeded(self):
        return self.calculate_credits_spent() >= self.credits_quota

    def can_login(self):
        return not self.is_deleted and self.is_active and not self.is_blocked

    def unseen_notifications(self):
        q = Notification.query
        if self.latest_seen_notification_ts:
            q = q.filter(Notification.broadcasted > self.latest_seen_notification_ts)
        return q.all()

    @staticmethod
    def verify_auth_token(token, app_secret):
        s = Serializer(app_secret)
        try:
            data = s.loads(token)
        except:
            return None
        user = User.query.get(data['id'])
        if user and user.can_login():
            return user

    def __repr__(self):
        return self.email

    def __hash__(self):
        return hash(self.email)


group_user = db.Table('groups_users', db.Column('group_id', db.String(32), db.ForeignKey('groups.id')), db.Column('user_id', db.String(32), db.ForeignKey('users.id')), db.PrimaryKeyConstraint('group_id', 'user_id'))
group_banned_user = db.Table('groups_banned_users', db.Column('group_id', db.String(32), db.ForeignKey('groups.id')), db.Column('user_id', db.String(32), db.ForeignKey('users.id')), db.PrimaryKeyConstraint('group_id', 'user_id'))
group_owner = db.Table('groups_owners', db.Column('group_id', db.String(32), db.ForeignKey('groups.id')), db.Column('owner_id', db.String(32), db.ForeignKey('users.id')), db.PrimaryKeyConstraint('group_id', 'owner_id'))


class Group(db.Model):
    __tablename__ = 'groups'

    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(32))
    _join_code = db.Column(db.String(64))
    description = db.Column(db.Text)
    _user_config = db.Column('user_config', db.Text)
    users = db.relationship('User', secondary=group_user, backref='groups', lazy='dynamic')
    banned_users = db.relationship('User', secondary=group_banned_user, backref='banned_groups', lazy='dynamic')
    owners = db.relationship('User', secondary=group_owner, backref='owned_groups', lazy='dynamic')
    blueprints = db.relationship('Blueprint', backref='group', lazy='dynamic')

    def __init__(self, name):
        self.id = uuid.uuid4().hex
        self.name = name
        self.join_code = name

    @hybrid_property
    def user_config(self):
        return load_column(self._user_config)

    @user_config.setter
    def user_config(self, value):
        self._user_config = json.dumps(value)

    @hybrid_property
    def join_code(self):
        return self._join_code

    @join_code.setter
    def join_code(self, name):
        self._join_code = name.replace(' ', '').lower() + uuid.uuid4().hex


class Notification(db.Model):
    __tablename__ = 'notifications'
    metadata = metadata

    id = db.Column(db.String(32), primary_key=True)
    broadcasted = db.Column(db.DateTime)
    subject = db.Column(db.String(MAX_NOTIFICATION_SUBJECT_LENGTH))
    message = db.Column(db.Text)

    def __init__(self):
        self.id = uuid.uuid4().hex
        self.broadcasted = datetime.datetime.utcnow()


class Keypair(db.Model):
    __tablename__ = 'keypairs'
    metadata = metadata

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.String(32), db.ForeignKey('users.id'))
    _public_key = db.Column(db.String(450))

    def __init__(self):
        self.id = uuid.uuid4().hex

    @hybrid_property
    def public_key(self):
        return self._public_key

    @public_key.setter
    def public_key(self, value):
        if not validate_ssh_pubkey(value):
            raise ValueError("Not a valid SSH public key")
        self._public_key = value


class ActivationToken(db.Model):
    __tablename__ = 'activation_tokens'
    metadata = metadata

    token = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.String(32), db.ForeignKey('users.id'))

    def __init__(self, user):
        self.token = uuid.uuid4().hex
        self.user_id = user.id


class Plugin(db.Model):
    __tablename__ = 'plugins'
    metadata = metadata

    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(32))
    _schema = db.Column('schema', db.Text)
    _form = db.Column('form', db.Text)
    _model = db.Column('model', db.Text)

    def __init__(self):
        self.id = uuid.uuid4().hex

    @hybrid_property
    def schema(self):
        return load_column(self._schema)

    @schema.setter
    def schema(self, value):
        self._schema = json.dumps(value)

    @hybrid_property
    def form(self):
        return load_column(self._form)

    @form.setter
    def form(self, value):
        self._form = json.dumps(value)

    @hybrid_property
    def model(self):
        return load_column(self._model)

    @model.setter
    def model(self, value):
        self._model = json.dumps(value)


class BlueprintTemplate(db.Model):
    __tablename__ = 'blueprint_templates'
    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(MAX_NAME_LENGTH))
    _config = db.Column('config', db.Text)
    is_enabled = db.Column(db.Boolean, default=False)
    plugin = db.Column(db.String(32), db.ForeignKey('plugins.id'))
    blueprints = db.relationship('Blueprint', backref='template', lazy='dynamic')
    _blueprint_schema = db.Column('blueprint_schema', db.Text)
    _blueprint_form = db.Column('blueprint_form', db.Text)
    _blueprint_model = db.Column('blueprint_model', db.Text)
    _allowed_attrs = db.Column('allowed_attrs', db.Text)

    def __init__(self):
        self.id = uuid.uuid4().hex

    @hybrid_property
    def config(self):
        return load_column(self._config)

    @config.setter
    def config(self, value):
        self._config = json.dumps(value)

    @hybrid_property
    def blueprint_schema(self):
        return load_column(self._blueprint_schema)

    @blueprint_schema.setter
    def blueprint_schema(self, value):
        self._blueprint_schema = json.dumps(value)

    @hybrid_property
    def blueprint_form(self):
        return load_column(self._blueprint_form)

    @blueprint_form.setter
    def blueprint_form(self, value):
        self._blueprint_form = json.dumps(value)

    @hybrid_property
    def blueprint_model(self):
        return load_column(self._blueprint_model)

    @blueprint_model.setter
    def blueprint_model(self, value):
        self._blueprint_model = json.dumps(value)

    @hybrid_property
    def allowed_attrs(self):
        return load_column(self._allowed_attrs)

    @allowed_attrs.setter
    def allowed_attrs(self, value):
        self._allowed_attrs = json.dumps(value)


class Blueprint(db.Model):
    __tablename__ = 'blueprints'
    metadata = metadata
    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(MAX_NAME_LENGTH))
    template_id = db.Column(db.String(32), db.ForeignKey('blueprint_templates.id'))
    _config = db.Column('config', db.Text)
    is_enabled = db.Column(db.Boolean, default=False)
    maximum_lifetime = db.Column(db.Integer, default=3600)
    preallocated_credits = db.Column(db.Boolean, default=False)
    cost_multiplier = db.Column(db.Float, default=1.0)
    instances = db.relationship('Instance', backref='blueprint', lazy='dynamic')
    group_id = db.Column(db.String(32), db.ForeignKey('groups.id'))

    def __init__(self):
        self.id = uuid.uuid4().hex

    @hybrid_property
    def config(self):
        return load_column(self._config)

    @config.setter
    def config(self, value):
        self._config = json.dumps(value)

    def cost(self, duration=None):
        if not duration:
            duration = self.maximum_lifetime

        return self.cost_multiplier * duration / 3600

    def __repr__(self):
        return self.name or "Unnamed blueprint"


class Instance(db.Model):
    STATE_QUEUEING = 'queueing'
    STATE_PROVISIONING = 'provisioning'
    STATE_RUNNING = 'running'
    STATE_DELETING = 'deleting'
    STATE_DELETED = 'deleted'
    STATE_FAILED = 'failed'

    VALID_STATES = (
        STATE_QUEUEING,
        STATE_PROVISIONING,
        STATE_RUNNING,
        STATE_DELETING,
        STATE_DELETED,
        STATE_FAILED,
    )

    __tablename__ = 'instances'
    metadata = metadata
    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.String(32), db.ForeignKey('users.id'))
    blueprint_id = db.Column(db.String(32), db.ForeignKey('blueprints.id'))
    name = db.Column(db.String(64), unique=True)
    public_ip = db.Column(db.String(64))
    client_ip = db.Column(db.String(64))
    provisioned_at = db.Column(db.DateTime)
    deprovisioned_at = db.Column(db.DateTime)
    errored = db.Column(db.Boolean, default=False)
    _state = db.Column('state', db.String(32))
    to_be_deleted = db.Column(db.Boolean, default=False)
    error_msg = db.Column(db.String(256))
    _instance_data = db.Column('instance_data', db.Text)

    def __init__(self, blueprint, user):
        self.id = uuid.uuid4().hex
        self.blueprint_id = blueprint.id
        self.blueprint = blueprint
        self.user_id = user.id
        self._state = Instance.STATE_QUEUEING

    def credits_spent(self, duration=None):
        if self.errored:
            return 0.0

        if not duration:
            duration = self.runtime

        if self.blueprint.preallocated_credits:
            duration = self.blueprint.maximum_lifetime

        try:
            cost_multiplier = self.blueprint.cost_multiplier
        except:
            logging.warn("invalid cost_multiplier for blueprint %s, defaulting to 1.0" % self.blueprint_id)
            cost_multiplier = 1.0

        return cost_multiplier * duration / 3600

    @hybrid_property
    def runtime(self):
        if not self.provisioned_at:
            return 0.0

        if not self.deprovisioned_at:
            diff = datetime.datetime.utcnow() - self.provisioned_at
        else:
            diff = self.deprovisioned_at - self.provisioned_at

        return diff.total_seconds()

    @hybrid_property
    def instance_data(self):
        return load_column(self._instance_data)

    @instance_data.setter
    def instance_data(self, value):
        self._instance_data = json.dumps(value)

    @hybrid_property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        if value in Instance.VALID_STATES:
            self._state = value
        else:
            raise ValueError("'%s' is not a valid state" % value)

    @staticmethod
    def generate_name(prefix):
        return '%s%s-the-%s' % (prefix, names.get_first_name().lower(), random.choice(NAME_ADJECTIVES))


class Lock(db.Model):
    __tablename__ = 'locks'
    metadata = metadata

    lock_id = db.Column(db.String(64), primary_key=True, unique=True)
    acquired_at = db.Column(db.DateTime)

    def __init__(self, lock_id):
        self.lock_id = lock_id
        self.acquired_at = datetime.datetime.utcnow()


class Variable(db.Model):
    __tablename__ = 'variables'
    metadata = metadata

    id = db.Column(db.String(32), primary_key=True)
    key = db.Column(db.String(MAX_VARIABLE_KEY_LENGTH), unique=True)
    _value = db.Column('value', db.String(MAX_VARIABLE_VALUE_LENGTH))
    readonly = db.Column(db.Boolean, default=False)
    t = db.Column(db.String(16))

    def __init__(self, k, v):
        self.id = uuid.uuid4().hex
        self.key = k
        if self.key in self.filtered_variables:
            self.readonly = True

        if type(v) in (int,):
            self.t = 'int'
        elif type(v) in (bool,):
            self.t = 'bool'
        else:
            self.t = 'str'

        self.value = v

    @classmethod
    def sync_local_config_to_db(cls, config_cls, config, force_sync=False):
        """
        Synchronizes keys from given config object to current database
        """

        try:
            # Prevent over-writing old entries in DB by accident
            if Variable.query.count() and not force_sync:
                return
        except OperationalError:
            logging.warn("Database structure not present! Run migrations or"
                         " configure db access!")
            return
        except InvalidRequestError:
            logging.warn("Database structure not present! Run migrations or"
                         " configure db access!")
            return
        for k in vars(config_cls).keys():
            if not k.startswith("_") and k.isupper() and k not in cls.blacklisted_variables:
                variable = Variable.query.filter_by(key=k).first()
                if not variable:
                    variable = Variable(k, config[k])
                    db.session.add(variable)
                else:
                    variable.key = k
                    variable.value = config[k]
        db.session.commit()

    @classmethod
    def string_to_bool(cls, v):
        if not v:
            return False
        return (v.lower() in ('true', u'true', '1'))

    @hybrid_property
    def value(self):
        if self.t == "str":
            return self._value
        elif self.t == 'bool':
            return Variable.string_to_bool(self._value)
        elif self.t == 'int':
            return int(self._value)

    @value.setter
    def value(self, v):
        if self.t == 'bool':
            try:
                if type(v) in (six.text_type, ):
                    self._value = Variable.string_to_bool(v)
                else:
                    self._value = bool(v)
            except Exception:
                logging.warn("invalid variable value for type %s: %s" % (self.t, v))
        elif self.t == 'int':
            try:
                self._value = int(v)
            except:
                logging.warn("invalid variable value for type %s: %s" % (self.t, v))
        else:
            self._value = v

        logging.debug('set %s to %s from input %s of type %s' % (self.key, self._value, v, type(v)))

    filtered_variables = (
        'SECRET_KEY', 'INTERNAL_API_BASE_URL', 'SQLALCHEMY_DATABASE_URI', 'WTF_CSRF_ENABLED',
        'MESSAGE_QUEUE_URI', 'SSL_VERIFY', 'ENABLE_SHIBBOLETH_LOGIN', 'PROVISIONING_NUM_WORKERS')

    blacklisted_variables = ('SECRET_KEY', 'SQLALCHEMY_DATABASE_URI')

    def __unicode__(self):
        return u"<Variable(%s, %s)>" % (self.key, self.value)

    def __str__(self):
        return "<Variable(%s, %s)>" % (self.key, self.value)

    def __repr__(self):
        return self.__str__()
