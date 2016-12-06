Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm provides the Contrail TSN and TOR agent service
Only OpenStack Icehouse or newer is supported.
Juju 2.0 is required.

Usage
-----

Contrail Configuration and Keystone are prerequisite services to
deploy.

Once ready, deploy and relate as follows:

    juju deploy contrail-tsn
    juju add-relation contrail-tsn:contrail-discovery contrail-configuration:contrail-discovery
    juju add-relation contrail-tsn:contrail-api contrail-configuration:contrail-api
    juju add-relation contrail-tsn keystone

Install Sources
---------------

The version of OpenContrail installed when deploying can be changed using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.

Control Node Relation
---------------------

This charm is typically related to contrail-configuration:contrail-discovery.
This instructs the Contrail vRouter agent to use the discovery service for
locating control nodes. This is the recommended approach.

Should the user wish to use vRouter configuration that specifies the location
of control nodes explicitly, not using the discovery service, they can relate
to a contrail-control charm:

    juju add-relation contrail-tsn contrail-control

TOR Agents:
----------
The following configuration needs to be configured for the tor agent

# IP address of the TOR
'tor_ip':'<ip address>',                                    
# Numeric value to uniquely identify the TOR
'tor_agent_id':'<id - a number>',                                                
# Unique name for TOR Agent. This is an optional field.
# If this is not specified, name used will be 
# <hostname>-<tor_agent_id>
'tor_agent_name':'nodexx-1',
# Always ovs
'tor_type':'ovs',                                     
# tcp or pssl (the latter from R2.2)
'tor_ovs_protocol':'pssl',                                     
# The TCP port to connect on the TOR (protocol = tcp);
# or ssl port on which TOR Agent listens, to which
# TOR connects (protocol = pssl) 
'tor_ovs_port':'<port>',                                   
# IP address of the TSN for this TOR
'tsn_ip':'<ip address>',
# Name of the TSN node
'tor_tsn_name': '<name>' ,
# Name of the TOR switch, should match the hostname on the TOR
'tor_name':'<switch name>',  
# IP address for Data tunnel endpoint
'tor_tunnel_ip':'ip address',  
# HTTP server port
'tor_agent_http_server_port': <port number>, 
# Vendor name for TOR Switch.       
'tor_vendor_name':'Juniper',
# Product name of TOR switch. This is an optional field.
'tor_product_name':'QFX5100'
