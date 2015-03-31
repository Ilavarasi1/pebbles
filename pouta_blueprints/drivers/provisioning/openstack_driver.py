import time
import json

from novaclient.v2 import client
import novaclient

from pouta_blueprints.drivers.provisioning import base_driver

SLEEP_BETWEEN_POLLS = 3
POLL_MAX_WAIT = 180


class OpenStackDriver(base_driver.ProvisioningDriverBase):
    def get_openstack_nova_client(self):
        openstack_env = self.create_openstack_env()
        os_username = openstack_env['OS_USERNAME']
        os_password = openstack_env['OS_PASSWORD']
        os_tenant_name = openstack_env['OS_TENANT_NAME']
        os_auth_url = openstack_env['OS_AUTH_URL']

        return client.Client(os_username, os_password, os_tenant_name, os_auth_url, service_type="compute")

    def get_configuration(self):
        from pouta_blueprints.drivers.provisioning.openstack_driver_config import CONFIG
        client = self.get_openstack_nova_client()

        images = [x.name for x in client.images.list()]
        flavors = [x.name for x in client.flavors.list()]

        config = CONFIG.copy()
        config['schema']['properties']['image']['enum'] = images
        config['schema']['properties']['flavor']['enum'] = flavors

        return config

    def do_update_connectivity(self, token, instance_id):
        instance = self.get_instance_data(token, instance_id)
        instance_data = instance['instance_data']
        instance_name = instance['name']

        nc = self.get_openstack_nova_client()
        nc.servers.get(instance_data['server_id'])
        sg = nc.security_groups.find(name='pb_%s' % instance_name)

        for rule in sg.rules:
            nc.security_group_rules.delete(rule["id"])

        nc.security_group_rules.create(
            sg.id,
            ip_protocol='tcp',
            from_port=22,
            to_port=22,
            cidr="%s/32" % instance['client_ip'],
            group_id=None
        )

    def do_provision(self, token, instance_id):
        instance = self.get_instance_data(token, instance_id)
        instance_name = instance['name']
        instance_user = instance['user_id']

        # fetch config
        blueprint_config = self.get_blueprint_description(token, instance['blueprint_id'])
        config = blueprint_config['config']

        write_log = self.create_prov_log_uploader(token, instance_id, log_type='provisioning')
        write_log("Provisioning OpenStack instance (%s)\n" % instance_id)

        # fetch user public key
        key_data = self.get_user_key_data(token, instance_user).json()
        if not key_data:
            error = 'user\'s public key is missing'
            error_body = {'state': 'failed', 'error_msg': error}
            self.do_instance_patch(token, instance_id, error_body)
            self.logger.debug(error)
            raise RuntimeError(error)

        nc = self.get_openstack_nova_client()
        image_name = config['image']
        try:
            image = nc.images.find(name=image_name)
        except novaclient.exceptions.NotFound:
            self.logger.debug('requested image %s not found' % image_name)

        write_log("Found requested image: %s\n" % image_name)

        flavor_name = config['flavor']
        try:
            flavor = nc.flavors.find(name=flavor_name)
        except novaclient.exceptions.NotFound:
            self.logger.debug('requested flavor %s not found' % flavor_name)

        write_log("Found requested flavor: %s\n" % flavor_name)

        key_name = 'pb_%s' % instance_user
        try:
            nc.keypairs.create(key_name, public_key=key_data[0]['public_key'])
        except:
            self.logger.debug('conflict: public key already exists')
            self.logger.debug('conflict: using existing key (pb_%s)' % instance_user)

        write_log("Creating security group\n")

        security_group_name = "pb_%s" % instance_name
        nc.security_groups.create(
            security_group_name,
            "Security group generated by Pouta Blueprints")

        write_log("Creating instance . . ")

        server = nc.servers.create(
            'pb_%s' % instance_name,
            image,
            flavor,
            key_name=key_name,
            security_groups=[security_group_name])

        while nc.servers.get(server.id).status is "BUILDING" or not nc.servers.get(server.id).networks:
            write_log(" . ")
            time.sleep(SLEEP_BETWEEN_POLLS)

        write_log("OK\nAssigning public IP\n")

        ips = nc.floating_ips.findall(instance_id=None)
        if not ips:
            write_log("No allocated free IPs left, trying to allocate one\n")
            ip = nc.floating_ips.create(pool="public")
        else:
            ip = ips[0]

        write_log("Got IP %s\n" % ip.ip)

        server.add_floating_ip(ip)
        instance_data = {
            'server_id': server.id,
            'floating_ip': ip.ip
        }
        write_log("Publishing server data\n")

        self.do_instance_patch(token, instance_id, {'instance_data': json.dumps(instance_data), 'public_ip': ip.ip})
        nc.keypairs.delete(key_name)
        write_log("Provisioning complete\n")

    def do_deprovision(self, token, instance_id):
        write_log = self.create_prov_log_uploader(token, instance_id, log_type='deprovisioning')
        write_log("Deprovisioning instance %s\n" % instance_id)
        instance = self.get_instance_data(token, instance_id)
        instance_data = instance['instance_data']
        instance_name = instance['name']
        nc = self.get_openstack_nova_client()

        write_log("Destroying server instance . . ")
        try:
            nc.servers.delete(instance_data['server_id'])
        except:
            write_log("Unable to delete server\n")

        delete_ts = time.time()
        while True:
            try:
                nc.servers.get(instance_data['server_id'])
                write_log(" . ")
                time.sleep(SLEEP_BETWEEN_POLLS)
            except:
                write_log("Server instance deleted\n")
                break

            if time.time() - delete_ts > POLL_MAX_WAIT:
                write_log("Server instance still running, giving up\n")
                break

        write_log("Releasing public IP\n")
        try:
            nc.floating_ips.delete(nc.floating_ips.find(ip=instance_data['floating_ip']).id)
        except:
            write_log("Unable to release public IP\n")

        write_log("Removing security group\n")
        try:
            sg = nc.security_groups.find(name="pb_%s" % instance_name)
            nc.security_groups.delete(sg.id)
        except:
            write_log("Unable to delete security group\n")

        write_log("Deprovisioning ready\n")
