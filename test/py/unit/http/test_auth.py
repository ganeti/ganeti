#
#

# Copyright (C) 2026 the Ganeti project
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

"""Unit tests for ganeti.http.auth module."""

import logging

from ganeti import rapi
from ganeti.http import auth


class TestPasswordFileUserPermissions:
  """Test cases for PasswordFileUser.has_permission() with different formats.

  Format: username password <@role|permissions|@role,+add,-remove>
  """

  def test_explicit_permissions(self):
    """Test explicit permission list: user password perm1,perm2,perm3"""
    users = auth.ParsePasswordFile(
      "user1 secret jobs.list,jobs.cancel,instances.list"
    )
    user = users["user1"]

    assert user.has_permission("jobs.list")
    assert user.has_permission("jobs.cancel")
    assert user.has_permission("instances.list")

    assert not user.has_permission("instances.create")
    assert not user.has_permission("nodes.list")
    assert not user.has_permission("cluster.info")

  def test_role_based_permissions(self):
    """Test role-based permissions: user password @admin"""
    users = auth.ParsePasswordFile("admin_user secret @admin")
    user = users["admin_user"]

    assert user.has_permission("jobs.list")
    assert user.has_permission("instances.create")
    assert user.has_permission("nodes.migrate")
    assert user.has_permission("cluster.info")

  def test_role_with_modifications(self):
    """Test role with additions and removals:
        user password @admin,+custom,-removed
    """
    users = auth.ParsePasswordFile(
      "modified_user secret @admin,+custom.permission,-jobs.cancel"
    )
    user = users["modified_user"]

    assert user.has_permission("jobs.list")
    assert user.has_permission("instances.create")

    assert user.has_permission("custom.permission")

    assert not user.has_permission("jobs.cancel")

  def test_unknown_role(self):
    """Test that unknown roles are ignored"""
    users = auth.ParsePasswordFile(
      "user1 secret @nonexistent_role,jobs.list"
    )
    user = users["user1"]

    assert user.has_permission("jobs.list")
    assert not user.has_permission("instances.create")

  def test_empty_options(self):
    """Test user with no permissions"""
    users = auth.ParsePasswordFile("user1 secret")
    user = users["user1"]

    assert not user.has_permission("jobs.list")
    assert not user.has_permission("instances.create")
    assert len(user.permissions) == 0

  def test_mixed_permissions_and_role(self):
    """Test mixed format: role + explicit permissions"""
    users = auth.ParsePasswordFile(
      "user1 secret @admin,extra.permission"
    )
    user = users["user1"]

    assert user.has_permission("jobs.list")
    assert user.has_permission("instances.create")

    assert user.has_permission("extra.permission")

  def test_deprecated_write_maps_to_admin(self):
    """Legacy 'write' option resolves to admin role permissions."""
    users = auth.ParsePasswordFile("user1 secret write")
    user = users["user1"]

    assert user.has_permission("instances.create")
    assert user.has_permission("cluster.modify")

  def test_deprecated_read_maps_to_readonly(self):
    """Legacy 'read' option resolves to readonly role permissions."""
    users = auth.ParsePasswordFile("user1 secret read")
    user = users["user1"]

    assert user.has_permission("instances.list")
    assert user.has_permission("cluster.info")
    assert not user.has_permission("instances.create")


class TestResolvePermissions:
  """Direct unit tests for _resolve_permissions."""

  def test_returns_frozenset(self):
    result = auth._resolve_permissions([], rapi.RAPI_ROLES)
    assert isinstance(result, frozenset)

  def test_empty_options(self):
    assert auth._resolve_permissions([], rapi.RAPI_ROLES) == frozenset()

  def test_order_independence_admin_then_remove(self):
    """@admin,-jobs.cancel and -jobs.cancel,@admin must give same result."""
    a = auth._resolve_permissions(["@admin", "-jobs.cancel"], rapi.RAPI_ROLES)
    b = auth._resolve_permissions(["-jobs.cancel", "@admin"], rapi.RAPI_ROLES)
    assert a == b
    assert "jobs.cancel" not in a

  def test_order_independence_complex(self):
    """All combinations of role+add+remove+explicit must canonicalize."""
    tokens = ["-jobs.cancel", "+custom.x", "@readonly", "extra.y"]
    expected = auth._resolve_permissions(tokens, rapi.RAPI_ROLES)
    # Reverse order produces the same set
    assert auth._resolve_permissions(list(reversed(tokens)),
                                     rapi.RAPI_ROLES) == expected
    assert "custom.x" in expected
    assert "extra.y" in expected
    assert "jobs.cancel" not in expected

  def test_remove_wins_over_add(self):
    """A token in both add and remove lists is removed."""
    result = auth._resolve_permissions(["+x.y", "-x.y"], rapi.RAPI_ROLES)
    assert "x.y" not in result

  def test_unknown_role_logs_warning(self, caplog):
    with caplog.at_level(logging.WARNING):
      result = auth._resolve_permissions(["@bogus"], rapi.RAPI_ROLES)
    assert result == frozenset()
    assert any("Unknown role '@bogus'" in r.getMessage()
               for r in caplog.records)

  def test_deprecated_write_logs_warning(self, caplog):
    with caplog.at_level(logging.WARNING):
      result = auth._resolve_permissions(["write"], rapi.RAPI_ROLES)
    assert result == rapi.RAPI_ACCESS_ALL
    assert any("Deprecated permission 'write'" in r.getMessage()
               for r in caplog.records)

  def test_deprecation_warning_dedups_within_load(self, caplog):
    """Two users with 'write' should produce one warning per file load."""
    contents = "user1 pw write\nuser2 pw write\nuser3 pw read\n"
    with caplog.at_level(logging.WARNING):
      auth.ParsePasswordFile(contents)
    write_warnings = [r for r in caplog.records
                      if "Deprecated permission 'write'" in r.getMessage()]
    read_warnings = [r for r in caplog.records
                     if "Deprecated permission 'read'" in r.getMessage()]
    assert len(write_warnings) == 1
    assert len(read_warnings) == 1


class TestOperatorRole:
  """The @operator role grants @readonly + start/stop/restart on instances."""

  def test_operator_is_readonly_superset(self):
    operator = rapi.RAPI_ROLES["operator"]
    readonly = rapi.RAPI_ROLES["readonly"]
    assert readonly < operator

  def test_operator_instance_operations(self):
    """Operator can perform non-config instance operations."""
    users = auth.ParsePasswordFile("op secret @operator")
    user = users["op"]
    allowed = [
      "instances.startup",
      "instances.shutdown",
      "instances.reboot",
      "instances.migrate",
      "instances.failover",
      "instances.replace_disks",
      "instances.export.prepare",
      "instances.export.create",
      "instances.export.remove",
      "instances.query.console",
    ]
    for perm in allowed:
      assert user.has_permission(perm), \
        f"@operator should have '{perm}'"

  def test_operator_inherits_readonly_queries(self):
    """Operator can still query everything @readonly can."""
    users = auth.ParsePasswordFile("op secret @operator")
    user = users["op"]
    assert user.has_permission("instances.list")
    assert user.has_permission("cluster.info")
    assert user.has_permission("nodes.query")

  def test_operator_cannot_modify_config(self):
    """Operator must NOT be able to create/modify/remove/rename."""
    users = auth.ParsePasswordFile("op secret @operator")
    user = users["op"]
    forbidden = [
      "instances.create",
      "instances.modify",
      "instances.remove",
      "instances.rename",
      "instances.recreate_disks",
      "instances.grow_disk",
      "cluster.modify",
      "cluster.redistribute_config",
      "nodes.modify",
      "nodes.role.modify",
      "nodes.migrate",
      "nodes.powercycle",
      "networks.create",
      "networks.modify",
      "networks.remove",
      "groups.create",
      "groups.modify",
      "groups.delete",
    ]
    for perm in forbidden:
      assert not user.has_permission(perm), \
        f"@operator should not have '{perm}'"
