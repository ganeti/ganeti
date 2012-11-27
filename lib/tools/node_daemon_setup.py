#
#

# Copyright (C) 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

"""Script to configure the node daemon.

"""

import os
import os.path
import optparse
import sys
import logging
import OpenSSL
from cStringIO import StringIO

from ganeti import cli
from ganeti import constants
from ganeti import errors
from ganeti import pathutils
from ganeti import utils
from ganeti import serializer
from ganeti import runtime
from ganeti import ht
from ganeti import ssconf


_DATA_CHECK = ht.TStrictDict(False, True, {
  constants.NDS_CLUSTER_NAME: ht.TNonEmptyString,
  constants.NDS_NODE_DAEMON_CERTIFICATE: ht.TNonEmptyString,
  constants.NDS_SSCONF: ht.TDictOf(ht.TNonEmptyString, ht.TString),
  constants.NDS_START_NODE_DAEMON: ht.TBool,
  })


class SetupError(errors.GenericError):
  """Local class for reporting errors.

  """


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  parser = optparse.OptionParser(usage="%prog [--dry-run]",
                                 prog=os.path.basename(sys.argv[0]))
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option(cli.DRY_RUN_OPT)

  (opts, args) = parser.parse_args()

  return VerifyOptions(parser, opts, args)


def VerifyOptions(parser, opts, args):
  """Verifies options and arguments for correctness.

  """
  if args:
    parser.error("No arguments are expected")

  return opts


def _VerifyCertificate(cert_pem, _check_fn=utils.CheckNodeCertificate):
  """Verifies a certificate against the local node daemon certificate.

  @type cert_pem: string
  @param cert_pem: Certificate and key in PEM format
  @rtype: string
  @return: Formatted key and certificate

  """
  try:
    cert = \
      OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
  except Exception, err:
    raise errors.X509CertError("(stdin)",
                               "Unable to load certificate: %s" % err)

  try:
    key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
  except OpenSSL.crypto.Error, err:
    raise errors.X509CertError("(stdin)",
                               "Unable to load private key: %s" % err)

  # Check certificate with given key; this detects cases where the key given on
  # stdin doesn't match the certificate also given on stdin
  x509_check_fn = utils.PrepareX509CertKeyCheck(cert, key)
  try:
    x509_check_fn()
  except OpenSSL.SSL.Error:
    raise errors.X509CertError("(stdin)",
                               "Certificate is not signed with given key")

  # Standard checks, including check against an existing local certificate
  # (no-op if that doesn't exist)
  _check_fn(cert)

  # Format for storing on disk
  buf = StringIO()
  buf.write(OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key))
  buf.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert))
  return buf.getvalue()


def VerifyCertificate(data, _verify_fn=_VerifyCertificate):
  """Verifies cluster certificate.

  @type data: dict
  @rtype: string
  @return: Formatted key and certificate

  """
  cert = data.get(constants.NDS_NODE_DAEMON_CERTIFICATE)
  if not cert:
    raise SetupError("Node daemon certificate must be specified")

  return _verify_fn(cert)


def VerifyClusterName(data, _verify_fn=ssconf.VerifyClusterName):
  """Verifies cluster name.

  @type data: dict
  @rtype: string
  @return: Cluster name

  """
  name = data.get(constants.NDS_CLUSTER_NAME)
  if not name:
    raise SetupError("Cluster name must be specified")

  _verify_fn(name)

  return name


def VerifySsconf(data, cluster_name, _verify_fn=ssconf.VerifyKeys):
  """Verifies ssconf names.

  @type data: dict

  """
  items = data.get(constants.NDS_SSCONF)

  if not items:
    raise SetupError("Ssconf values must be specified")

  # TODO: Should all keys be required? Right now any subset of valid keys is
  # accepted.
  _verify_fn(items.keys())

  if items.get(constants.SS_CLUSTER_NAME) != cluster_name:
    raise SetupError("Cluster name in ssconf does not match")

  return items


def LoadData(raw):
  """Parses and verifies input data.

  @rtype: dict

  """
  return serializer.LoadAndVerifyJson(raw, _DATA_CHECK)


def Main():
  """Main routine.

  """
  opts = ParseOptions()

  utils.SetupToolLogging(opts.debug, opts.verbose)

  try:
    getent = runtime.GetEnts()

    data = LoadData(sys.stdin.read())

    cluster_name = VerifyClusterName(data)
    cert_pem = VerifyCertificate(data)
    ssdata = VerifySsconf(data, cluster_name)

    logging.info("Writing ssconf files ...")
    ssconf.WriteSsconfFiles(ssdata, dry_run=opts.dry_run)

    logging.info("Writing node daemon certificate ...")
    utils.WriteFile(pathutils.NODED_CERT_FILE, data=cert_pem,
                    mode=pathutils.NODED_CERT_MODE,
                    uid=getent.masterd_uid, gid=getent.masterd_gid,
                    dry_run=opts.dry_run)

    if (data.get(constants.NDS_START_NODE_DAEMON) and # pylint: disable=E1103
        not opts.dry_run):
      logging.info("Restarting node daemon ...")

      cmd = ("%s stop-all; %s start %s" %
             (pathutils.DAEMON_UTIL, pathutils.DAEMON_UTIL, constants.NODED))

      result = utils.RunCmd(cmd, interactive=True)
      if result.failed:
        raise SetupError("Could not start the node daemon, command '%s'"
                         " failed: %s" % (result.cmd, result.fail_reason))

    logging.info("Node daemon successfully configured")
  except Exception, err: # pylint: disable=W0703
    logging.debug("Caught unhandled exception", exc_info=True)

    (retcode, message) = cli.FormatError(err)
    logging.error(message)

    return retcode
  else:
    return constants.EXIT_SUCCESS
