==================================
Ganeti Terraform Provider Proposal
==================================

:Created: 2023-Feb-23
:Status: Draft

.. toctree::
   :hidden:

1. Introduction
---------------

This document proposes the creation of a Terraform provider for Ganeti, 
a cluster virtualization management software. The provider will 
allow users to manage their Ganeti infrastructure as code, 
using the Terraform configuration language and tool. 
The provider will be implemented using the Terraform provider SDK 
and the Ganeti Remote API.

2. Background
-------------

Terraform is an infrastructure-as-code tool that enables users to manage
and provision cloud infrastructure using a declarative configuration 
language. Terraform is platform-agnostic and supports a wide range of 
infrastructure providers, including major cloud providers such as AWS, 
Azure, and Google Cloud. 
Terraform providers are plugins that extend Terraform's capabilities 
to support new infrastructure platforms or services.

Ganeti is a cluster virtualization management software that allows users
to create and manage virtual machines (VMs) on a cluster of 
physical hosts. Ganeti provides a number of features, such as automatic 
failover, live migration, and DRBD-based disk replication. 
Ganeti also has a Remote API that enables users to manage their Ganeti 
cluster programmatically.

3. Scope
--------

The proposed Ganeti Terraform provider will support the following Ganeti
resources:

- `ganeti_instance`: A Ganeti virtual machine instance, running on a 
  physical host (node).

The provider will support basic create, read, update, and delete (CRUD)
operations for these resources, as well as importing existing resources 
into Terraform state. The provider will also support dependencies 
between resources, such as instances depending on a other instance.

1. Requirements
---------------

The following requirements must be met in order to create the Ganeti 
Terraform provider:

- Access to a Ganeti cluster, with the Ganeti Remote API enabled and 
  configured.
- Knowledge of the Terraform provider SDK and the Go programming
  language.
- Familiarity with the Ganeti Remote API and the Ganeti command-line 
  interface (CLI).
- Experience with creating and managing Terraform providers, 
  or similar infrastructure-as-code tools.

1. Architecture
---------------

The Ganeti Terraform provider will be implemented as a plugin for 
Terraform, using the Terraform provider SDK and the Ganeti Remote API. 
The provider will consist of a set of Go packages that implement the 
necessary CRUD operations for each Ganeti resource. 
The provider will communicate with the Ganeti cluster using the 
Remote API, which provides a RESTful interface for managing Ganeti 
resources.

The provider will also include a schema that defines the configuration 
options for each resource, as well as the dependencies between resources. 
The schema will be used to validate and parse user-provided 
configuration files, and to generate documentation for the provider.

6. Implementation
------------------

The following steps must be taken in order to implement the Ganeti 
Terraform provider:

- Familiarize oneself with the Terraform provider SDK and the Go 
  programming language.
- Study the Ganeti Remote API and the Ganeti command-line 
  interface (CLI).
- Implement Go packages for each Ganeti resource, using the Remote API 
  to manage the resources.
- Define a schema for each resource, using the Terraform schema language.
- Write unit tests and integration tests for each resource.
- Implement a provider package that registers the resources and their 
  dependencies with Terraform.
- Package the provider as a binary plugin that can be loaded by Terraform.

1. Testing
----------

The Ganeti Terraform provider

will be tested using a combination of unit tests and integration tests. 
Unit tests will be written for each Go package that implements CRUD 
operations for a Ganeti resource. Integration tests will be written to 
test the provider's behavior as a whole, including creating, updating, 
and deleting resources.

The provider will also be tested against different versions of the 
Ganeti Remote API, to ensure compatibility with different Ganeti 
clusters. The provider will also be tested against different Terraform 
versions, to ensure compatibility with different versions of Terraform.

8. Limitations
--------------

The following limitations apply to the Ganeti Terraform provider:

- The provider only supports a limited set of Ganeti resources, 
  specifically instances, and disks. Other resources, such as Cluster, 
  networks or templates, are not currently supported.
- The provider does not currently support all the features of the 
  Ganeti Remote API, such as job monitoring or cluster configuration.
- The provider may have limitations with regard to scalability or 
  performance, depending on the size of the Ganeti cluster and the 
  number of resources being managed.

1. Conclusion
-------------

The proposed Ganeti Terraform provider will enable users to manage their
Ganeti infrastructure as code, using the Terraform configuration 
language and tool. The provider will support basic CRUD operations for 
clusters, instances, and disks, as well as dependencies between 
resources. The provider will be implemented using the Terraform provider
SDK and the Ganeti Remote API, and will be tested using a combination 
of unit tests and integration tests.

10. References
--------------

- Terraform: https://www.terraform.io/
- Ganeti: https://ganeti.github.io/
- Ganeti Remote API: https://docs.ganeti.org/docs/ganeti/2.17/html/rapi.html
- Terraform Provider SDK: https://www.terraform.io/docs/extend/plugin-sdk.html
- Go programming language: https://golang.org/
- Terraform schema language: https://www.terraform.io/docs/language/types/schema.html

11. Appendix: Example Configuration
-----------------------------------

Here is an example Terraform configuration that uses the Ganeti provider
to manage a Ganeti instance:

::
   provider "ganeti" {
    endpoint = "https://ganeti-cluster.example.com:5080"
    username = "admin"
    password = "s3cr3t"
  }
    
  resource "ganeti_instance" "myinstance" {
    name      = "myinstance.example.com"
    cluster   = ganeti_cluster.mycluster.id
    os_type   = "debian10"
    disk_size = 4096
    nics {
      network = "default"
      ip = "pool"
    }
  }
