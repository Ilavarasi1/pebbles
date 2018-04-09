Drivers
*******

.. General instructions: document in the source with the structure of this
   document in mind, then import here.

Overview
========

.. automodule:: pebbles.drivers.provisioning

Base Driver
===========

.. automodule:: pebbles.drivers.provisioning.base_driver

.. autoclass:: pebbles.drivers.provisioning.base_driver.ProvisioningDriverBase

There are four drivers that are currently suppported in pebbles


1. OpenStack Driver (include OpenStack Driver rst file)
-------------------------------------------------------

.. automodule:: pebbles.drivers.provisioning.openstack_driver

.. autoclass:: pebbles.drivers.provisioning.openstack_driver.OpenStackDriver


2. OpenShift Driver
-------------------

.. automodule:: pebbles.drivers.provisioning.openshift_driver

.. autoclass:: pebbles.drivers.provisioning.openshift_driver.OpenShiftDriver

3. Docker Driver:
-----------------

:doc:`README_docker_driver`

4. Dummy Drivear(*testing purposes*)
------------------------------------

.. autoclass:: pebbles.drivers.provisioning.dummy_driver.DummyDriver


