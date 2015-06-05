#!/usr/bin/python
#

# Copyright (C) 2015 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Script for testing ganeti.tools.ssl_update"""

import unittest
import shutil
import tempfile
import os.path
import OpenSSL
import time

from ganeti import errors
from ganeti import constants
from ganeti import serializer
from ganeti import pathutils
from ganeti import compat
from ganeti import utils
from ganeti.tools import ssl_update

import testutils


class TestGenerateClientCert(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

    self.client_cert = os.path.join(self.tmpdir, "client.pem")

    self.server_cert = os.path.join(self.tmpdir, "server.pem")
    some_serial_no = int(time.time())
    utils.GenerateSelfSignedSslCert(self.server_cert, some_serial_no)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testRegnerateClientCertificate(self):
    my_node_name = "mynode.example.com"
    data = {constants.NDS_CLUSTER_NAME: "winnie_poohs_cluster",
            constants.NDS_NODE_DAEMON_CERTIFICATE: "some_cert",
            constants.NDS_NODE_NAME: my_node_name}

    ssl_update.RegenerateClientCertificate(data, client_cert=self.client_cert,
                                           signing_cert=self.server_cert)

    client_cert_pem = utils.ReadFile(self.client_cert)
    server_cert_pem = utils.ReadFile(self.server_cert)
    client_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                  client_cert_pem)
    signing_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                   server_cert_pem)
    self.assertEqual(client_cert.get_issuer().CN, signing_cert.get_subject().CN)
    self.assertEqual(client_cert.get_subject().CN, my_node_name)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
