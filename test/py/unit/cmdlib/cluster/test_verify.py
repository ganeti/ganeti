import pytest
from unittest.mock import patch, MagicMock
from ganeti import utils
from ganeti.cmdlib.cluster.verify import LUClusterVerifyGroup

# a group UUID
GROUP_UUID = '52978ad9-238c-41cd-9ed0-23df1ec18d64'

# simulate RunCmd()
class MockRunCmd:
  def __init__(self, stdout):
    self.stdout = stdout

  def RunCmd(self, cmd):
    return self.stdout

# template output of hcheck
TEST_STRING_TEMPLATE = (
  f"HCHECK_GROUP_UUID_0='{GROUP_UUID}'\n"
  "HCHECK_INIT_GROUP_0_N1_FAIL={n1_fail}\n"
  "HCHECK_INIT_GROUP_0_CONFLICT_TAGS=0\n"
  "HCHECK_INIT_GROUP_0_OFFLINE_PRI=0\n"
  "HCHECK_INIT_GROUP_0_OFFLINE_SEC=0\n"
  "HCHECK_INIT_GROUP_0_GN1_FAIL={gn1_fail}\n"
  "HCHECK_INIT_GROUP_0_SCORE=2.41772341"
)

@pytest.fixture
def lu_cluster_verify_group():
  processor = MagicMock()
  op = MagicMock()
  cfg = MagicMock()
  rpc_runner = MagicMock()
  wconfdcontext = MagicMock()
  wconfd = MagicMock()

  lu_cluster_verify_group = LUClusterVerifyGroup(
    processor, op, cfg, rpc_runner, wconfdcontext, wconfd)
  lu_cluster_verify_group._Error = MagicMock()
  return lu_cluster_verify_group

@pytest.mark.parametrize("n1_fail, gn1_fail, expected_error_calls", [
  (0, 0, 0),
  (2, 0, 1),
  (0, 3, 1),
  (4, 5, 1)
])
def test_VerifyNPlusOneMemory(lu_cluster_verify_group, n1_fail, gn1_fail,
                              expected_error_calls):
  stdout = TEST_STRING_TEMPLATE.format(n1_fail=n1_fail, gn1_fail=gn1_fail)
  mock_run_cmd = MockRunCmd(stdout)
  with patch('ganeti.utils.RunCmd', return_value=mock_run_cmd):
    result = lu_cluster_verify_group._VerifyNPlusOneMemory(GROUP_UUID)
    assert lu_cluster_verify_group._Error.call_count == expected_error_calls, (
      f"Testcase n1_fail={n1_fail}, gn1_fail={gn1_fail} failed")

