"""
Image handler for rbd-backed images.
"""

from nova.virt.imagehandler import base
from nova.virt.libvirt import rbd_utils

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

CONF = cfg.CONF
CONF.import_opt('libvirt_images_rbd_pool', 'nova.virt.libvirt.imagebackend')
CONF.import_opt('libvirt_images_rbd_ceph_conf',
                'nova.virt.libvirt.imagebackend')
CONF.import_opt('rbd_user', 'nova.virt.libvirt.volume')
CONF.import_opt('rbd_secret_uuid', 'nova.virt.libvirt.volume')

LOG = logging.getLogger(__name__)


class RBDImageHandler(base.ImageHandler, rbd_utils.RBDDriver):
    """Handler for rbd-backed images.
    """
    def __init__(self, driver=None, *args, **kwargs):
        super(RBDImageHandler, self).__init__(driver, *args, **kwargs)
        if not CONF.libvirt_images_rbd_pool:
            raise RuntimeError(_('You should specify'
                                 ' libvirt_images_rbd_pool'
                                 ' flag to use rbd images.'))
        self._configure(
            pool=CONF.libvirt_images_rbd_pool,
            ceph_conf=CONF.libvirt_images_rbd_ceph_conf,
            rbd_user=CONF.rbd_user,
            rbd_lib=kwargs.get('rbd'),
            rados_lib=kwargs.get('rados'),
            )

    def get_schemes(self):
        return ('rbd')

    def _fetch_image(self, context, image_id, path,
                     user_id=None, project_id=None, location=None,
                     backend_dest=None):
        if backend_dest is None or not self._is_cloneable(location):
            return False
        dest_pool, dest_image = backend_dest
        prefix, pool, image, snapshot = self._parse_location(location)
        self._clone(dest_pool, dest_image, pool, image, snapshot)
        return True
