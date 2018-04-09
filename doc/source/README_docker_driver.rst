:orphan:

DockerDriver
************

Getting started
===============

After following the standard install instructions and when DockerDriver is enabled using PLUGIN_WHITELIST, the driver can be seen in the 'Configure' tab under 'Plugins' section. Additional steps are required to activate docker driver.


Step 1: Pull a docker image:
============================

First, the docker images will need to be downloaded (using docker pull from dockerhub) and placed in pebbles server's /var/lib/pb/docker_images -directory. At the time of writing, docker driver will upload the image saved in this directory to new host/pool VMs (instead of hosts pulling them from a private Docker registry).

As cloud-user on the pebbles server, pull the images e.g::
    
    docker pull rocker/rstudio

Then save the image to image directory (/var/lib/pb/docker_images by default)::

    docker save rocker/rstudio > /var/lib/pb/docker_images/rocker.rstudio.img

It's essential that you write directly to /var/lib/pb/docker_images/ so the SELinux labels are created properly.

.. note::
         Images from the image directory are pushed to notebook hosts only when they are being prepared.

.. note::
         All images are pushed to each notebook pool hosts (which may host several containers) when the host is prepared to be ACTIVE.


Step 2: Configure the Docker Driver:
==========================================

In the web-ui , go to 'Dashboard', then click 'Driver Configs' tab. This lists the configurations specific to DockerDriver and the hosts.

.. automodule:: pebbles.drivers.provisioning.docker_driver

As an Admin, We can check the number of pool hosts and their details in the UI by clicking 'Dashboard' and then 'Driver Hosts' tab. It is also possible to update some configurations of individual pool hosts by using 'Update Config' button.

Step 3: Create a Docker Driver Plugin 
=====================================

Go to web-UI, click 'Configure', then Click "Create Template" next to DockerDriver under 'Plugins'. Now the configurations for this specific template can be done.

Docker instance configs:
------------------------

**Name:** Name of the template  
**description:** Description  
**docker image:** You can choose the image that you want to upload to the pool hosts. The images listed here are from /var/lib/pb/docker_images directory.  
**internal_port:**  
**launch_command:**  
**environment variables for docker, separated by space:** Here you can customise the environment for the users. You can clone a github repo, download data sets, install custom libraries through bash scripts. e.g  
**Show the required password/token (if any), to the user:**  
**memory_limit:**  
**consumed_slots:**   
**Maximum instances per user:** The number of instances any user is allowed to launch at a time.  
**Maximum life-time (days hours mins):** Lifetime of the instances launched.  
**Cost multiplier (default 1.0):**  
**needs_ssh_keys:**  

**Proxy Options:**  

*Bypass Token Authentication (Jupyter Notebooks):*  
*Redirect the proxy url:*  
*Rewrite the proxy url:*  
*Set host header:*  

You can also let group owners to override these configurations by checking "Select Attributes to override".  

Step 4: Create a blueprint template  
===================================

Go to Web UI, select 'Configure' tab, click on 'Create Blueprint' next to DockerDriver  

Settings:

* Name: docker-rstudio-10m
* Description: Rocker RStudio image, use rstudio/rstudio as credentials
* docker_image: rocker/rstudio
* Internal port: 8787
* Maximum lifetime: 10m

Save and activate, go to 'Dashboard' and launch an instance. Once the instance is running, click 'Open in Browser'


Step 5: Shutting down the server
================================

.. DANGER::
    DockerDriver needs to be in shutdown mode before shutting down the system. Otherwise there is a risk of leaving zombie servers!

Because DockerDriver maintains a pool of VMs to host the containers, you will have to shut it down in an orderly
fashion for all the allocated resources to be deleted/released. Before shutting down the main server, simply set::
 
    DD_SHUTDOWN_MODE: True
    
and the driver will delete the resources in the pool. In case there is an runaway container and the hosts are not
empty, you will have to manually delete the VM, security group and volume from OpenStack.


Step 6: Custom blueprints
=========================

There is/will be a repository with the notebook images we use. It's located at
TBD. To build one of the images clone the repo and run::

        docker build .
