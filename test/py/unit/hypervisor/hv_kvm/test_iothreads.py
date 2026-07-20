import pytest
from unittest import mock
from ganeti import constants
from ganeti.hypervisor import hv_kvm

@pytest.fixture
def mock_kvm_hypervisor():
    hv = mock.Mock(spec=hv_kvm.KVMHypervisor)
    hv._CalcVirtioDiskIothreads = hv_kvm.KVMHypervisor._CalcVirtioDiskIothreads.__get__(hv)

    hv._CheckDeviceFeature = mock.Mock()

    hv._KVMOPT_DEVICEHELP_VIRTIO_BLK = "blk_help"
    hv._VIRTIO_BLK_IOTHREAD_VQ_MAPPING = mock.Mock()
    return hv


def test_legacy_instance_returns_zero(mock_kvm_hypervisor):
    """Instances started pre upgrade have no iothread in up_hvp"""
    up_hvp = {
        constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_NATIVE,
        constants.HV_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL
    }
    vcpus = 4
    assert mock_kvm_hypervisor._CalcVirtioDiskIothreads(up_hvp, vcpus) == 0


def test_invalid_aio_returns_zero(mock_kvm_hypervisor):
    """with aio set to 'threads', disable IOThreads"""
    up_hvp = {
        constants.HV_VIRTIO_DISK_IOTHREADS: 2,
        constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_THREADS,
        constants.HV_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL,
    }
    vcpus = 4
    assert mock_kvm_hypervisor._CalcVirtioDiskIothreads(up_hvp, vcpus) == 0


def test_multiqueue_supported(mock_kvm_hypervisor):
    """when QEMU supports vq-mapping (virtio-blk)"""
    mock_kvm_hypervisor._CheckDeviceFeature.return_value = True

    up_hvp = {
        constants.HV_VIRTIO_DISK_IOTHREADS: 4,
        constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_IO_URING,
        constants.HV_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL,
        constants.HV_KVM_PATH: "/usr/bin/qemu-system-x86_64"
    }
    vcpus = 4
    assert mock_kvm_hypervisor._CalcVirtioDiskIothreads(up_hvp, vcpus) == 4

def test_multiqueue_supported_less_vpcus(mock_kvm_hypervisor):
    """when QEMU supports vq-mapping (virtio-blk), but has less vCPUs"""
    mock_kvm_hypervisor._CheckDeviceFeature.return_value = True

    up_hvp = {
        constants.HV_VIRTIO_DISK_IOTHREADS: 4,
        constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_IO_URING,
        constants.HV_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL,
        constants.HV_KVM_PATH: "/usr/bin/qemu-system-x86_64"
    }
    vcpus = 2
    assert mock_kvm_hypervisor._CalcVirtioDiskIothreads(up_hvp, vcpus) == vcpus

def test_multiqueue_fallback_to_one(mock_kvm_hypervisor):
    """when QEMU does not support vq-mapping (virtio-scsi)"""
    mock_kvm_hypervisor._CheckDeviceFeature.return_value = False

    up_hvp = {
        constants.HV_VIRTIO_DISK_IOTHREADS: 4,
        constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_NATIVE,
        constants.HV_DISK_TYPE: constants.HT_DISK_SCSI_HD,
        constants.HV_KVM_SCSI_CONTROLLER_TYPE: constants.HT_SCSI_CONTROLLER_VIRTIO,
        constants.HV_KVM_PATH: "/usr/bin/qemu-system-x86_64"
    }
    vcpus = 4
    assert mock_kvm_hypervisor._CalcVirtioDiskIothreads(up_hvp, vcpus) == 1
