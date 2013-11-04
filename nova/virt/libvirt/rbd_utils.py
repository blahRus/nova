import json
import urllib

from nova import exception
from nova.openstack.common.gettextutils import _ # noqa
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None


class ImageUnacceptable(Exception):
    def __init__(self, **kwargs):
        message = "Image %(image_id)s is unacceptable: %(reason)s" % kwargs
        super(ImageUnacceptable, self).__init__(message)


class RBDVolumeProxy(object):
    """Context manager for dealing with an existing rbd volume.

    This handles connecting to rados and opening an ioctx automatically, and
    otherwise acts like a librbd Image object.

    The underlying librados client and ioctx can be accessed as the attributes
    'client' and 'ioctx'.
    """
    def __init__(self, driver, name, pool=None, snapshot=None,
                 read_only=False):
        client, ioctx = driver._connect_to_rados(pool)
        try:
            snap_name = None
            if snapshot is not None:
                snap_name = snapshot.encode('utf8') 
            self.volume = driver.rbd.Image(ioctx, name.encode('utf8'),
                                           snapshot=snap_name,
                                           read_only=read_only)
        except driver.rbd.Error:
            LOG.exception(_("error opening rbd image %s"), name)
            driver._disconnect_from_rados(client, ioctx)
            raise
        self.driver = driver
        self.client = client
        self.ioctx = ioctx

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        try:
            self.volume.close()
        finally:
            self.driver._disconnect_from_rados(self.client, self.ioctx)

    def __getattr__(self, attrib):
        return getattr(self.volume, attrib)


class RADOSClient(object):
    """Context manager to simplify error handling for connecting to ceph."""
    def __init__(self, driver, pool=None):
        self.driver = driver
        self.cluster, self.ioctx = driver._connect_to_rados(pool)

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.driver._disconnect_from_rados(self.cluster, self.ioctx)


class RBDDriver(object):

    def _configure(self, pool, ceph_conf, rbd_user,
                   rbd_lib=None, rados_lib=None):
        self.pool = pool.encode('utf8')
        self.ceph_conf = ceph_conf.encode('utf8') if ceph_conf else None
        self.rbd_user = rbd_user.encode('utf8') if rbd_user else None
        self.rbd = rbd_lib or rbd
        self.rados = rados_lib or rados

    def _connect_to_rados(self, pool=None):
        client = self.rados.Rados(rados_id=self.rbd_user,
                                  conffile=self.ceph_conf)
        try:
            client.connect()
            pool_to_open = pool.encode('utf8') or self.pool
            ioctx = client.open_ioctx(pool_to_open)
            return client, ioctx
        except self.rados.Error:
            # shutdown cannot raise an exception
            client.shutdown()
            raise

    def _disconnect_from_rados(self, client, ioctx):
        # closing an ioctx cannot raise an exception
        ioctx.close()
        client.shutdown()

    def _get_mon_addrs(self):
        args = ['ceph', 'mon', 'dump', '--format=json']
        args.extend(self._ceph_args())
        out, _ = self._execute(*args)
        lines = out.split('\n')
        if lines[0].startswith('dumped monmap epoch'):
            lines = lines[1:]
        monmap = json.loads('\n'.join(lines))
        addrs = [mon['addr'] for mon in monmap['mons']]
        hosts = []
        ports = []
        for addr in addrs:
            host_port = addr[:addr.rindex('/')]
            host, port = host_port.rsplit(':', 1)
            hosts.append(host.strip('[]'))
            ports.append(port)
        return hosts, ports

    def _ceph_args(self):
        return ['--id', self.rbd_user, '--conf', self.ceph_conf]

    def _supports_layering(self):
        return hasattr(self.rbd, 'RBD_FEATURE_LAYERING')

    def _parse_location(self, location):
        prefix = 'rbd://'
        if not location.startswith(prefix):
            reason = _('Not stored in rbd')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        pieces = map(urllib.unquote, location[len(prefix):].split('/'))
        if any(map(lambda p: p == '', pieces)):
            reason = _('Blank components')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        if len(pieces) != 4:
            reason = _('Not an rbd snapshot')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        return pieces

    def _get_fsid(self):
        with RADOSClient(self) as client:
            return client.cluster.get_fsid()

    def _is_cloneable(self, image_location):
        try:
            fsid, pool, image, snapshot = self._parse_location(image_location)
        except exception.ImageUnacceptable as e:
            LOG.debug(_('not cloneable: %s'), e)
            return False

        if self._get_fsid() != fsid:
            reason = _('%s is in a different ceph cluster') % image_location
            LOG.debug(reason)
            return False

        # check that we can read the image
        try:
            with RBDVolumeProxy(self, image,
                                pool=pool,
                                snapshot=snapshot,
                                read_only=True):
                return True
        except self.rbd.Error as e:
            LOG.debug(_('Unable to open image %(loc)s: %(err)s') %
                      dict(loc=image_location, err=e))
            return False

    def _clone(self, dest_pool, dest_image, src_pool, src_image, src_snap):
        LOG.debug(_('cloning %(pool)s/%(img)s@%(snap)s to %(dstpl)/%(dst)s') %
                  dict(pool=src_pool, img=src_image, snap=src_snap,
                       dst=dest_image, dstpl=dest_pool))
        with RADOSClient(self, src_pool) as src_client:
            with RADOSClient(self, dest_pool) as dest_client:
                self.rbd.RBD().clone(src_client.ioctx,
                                     src_image.encode('utf-8'),
                                     src_snap.encode('utf-8'),
                                     dest_client.ioctx,
                                     dest_image.encode('utf-8'),
                                     features=self.rbd.RBD_FEATURE_LAYERING)

    def _resize(self, name, size_bytes):
        with RBDVolumeProxy(self, name) as vol:
            vol.resize(size_bytes)
