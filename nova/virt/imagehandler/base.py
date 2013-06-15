# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2013 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Base image handler implementation.
"""

import abc
import sys

import six

from nova.openstack.common.gettextutils import _
from nova.openstack.common import lockutils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class ImageHandler(object):
    """Image handler base class.

    Currently the behavior of this image handler class just
    only like a image fetcher. On next step, we could implement
    particular sub-class in relevant hypervisor layer with more
    advanced functions base on this structure, such as
    CoW creating and snapshot capturing, etc..
    """

    def __init__(self, driver, *args, **kwargs):
        """Construct a image handler instance.

        :param driver: a valid compute driver instance,
                such as nova.virt.libvirt.driver.LibvirtDriver object
        :param associate_fn: An optional hook function, will be called when
                an image be handled by this handler.
        :param disassociate_fn: An optional hook function, will be called when
                the associated relationship be removed.
        """
        self._last_ops_handled = False
        self.driver = driver
        noop = lambda *args, **kwargs: None
        self.associate_fn = kwargs.get('associate_fn', noop)
        self.disassociate_fn = kwargs.get('disassociate_fn', noop)

    @abc.abstractmethod
    def get_schemes(self):
        """Returns a tuple of schemes which this handler can handle."""
        pass

    def fetch_image(self, context, image_id, path,
                    user_id=None, project_id=None, location=None):
        """Fetch an image from a location to local.

        :param context: Request context
        :param image_id: The opaque image identifier
        :param path: The image data to write, as a file-like object
        :param user_id: Request user id
        :param project_id: Request project id
        :param location: Image location to handling

        :retval a boolean value to inform handling success or not
        """
        with lockutils.lock("nova-imagehandler-%s" % image_id,
                            lock_file_prefix='nova-', external=True):
            ret = self._fetch_image(context, image_id, path,
                                    user_id, project_id, location)
            if ret:
                self._associate(path, location)
            self._set_handled(ret)

    def remove_image(self, path,
                     context=None, image_id=None,
                     user_id=None, project_id=None,
                     location=None):
        """Remove an image from local.

        :param path: The image object local storage path
        :param context: Request context
        :param image_id: The opaque image identifier
        :param user_id: Request user id
        :param project_id: Request project id
        :param location: Image location to handling

        :retval a boolean value to inform handling success or not
        """
        with lockutils.lock("nova-imagehandler-%s" % image_id,
                            lock_file_prefix='nova-', external=True):
            ret = self._remove_image(path, context, image_id,
                                     user_id, project_id, location)
            if ret:
                self._disassociate(path)
            self._set_handled(ret)

    def move_image(self, src_path, dst_path,
                   context=None, image_id=None, user_id=None, project_id=None,
                   location=None):
        """Move an image on local.

        :param src_path: The image object source path
        :param dst_path: The image object destination path
        :param context: Request context
        :param image_id: The opaque image identifier
        :param user_id: Request user id
        :param project_id: Request project id
        :param location: Image location to handling

        :retval a boolean value to inform handling success or not
        """
        with lockutils.lock("nova-imagehandler-%s" % image_id,
                            lock_file_prefix='nova-', external=True):
            ret = self._move_image(src_path, dst_path, context, image_id,
                                   user_id, project_id, location)
            if ret:
                self._disassociate(src_path)
                self._associate(dst_path, location)
            self._set_handled(ret)

    def last_ops_handled(self, flush=True):
        ret = self._last_ops_handled
        if flush:
            self._last_ops_handled = False
        return ret

    def _set_handled(self, handled):
        self._last_ops_handled = handled

    @abc.abstractmethod
    def _fetch_image(self, context, image_id, path,
                     user_id=None, project_id=None, location=None):
        """Fetch an image from a location to local.
        Specific handler can using full-copy or zero-copy approach to
        implement this method.

        :param context: Request context
        :param image_id: The opaque image identifier
        :param path: The image data to write, as a file-like object
        :param user_id: Request user id
        :param project_id: Request project id
        :param location: Image location to handling

        :retval a boolean value to inform handling success or not
        """
        pass

    @abc.abstractmethod
    def _remove_image(self, path,
                      context=None, image_id=None,
                      user_id=None, project_id=None, location=None):
        """Remove an image from local.
        Specific handler can using particular approach to
        implement this method which base on '_fetch_image()' implementation.

        :param path: The image object local storage path
        :param context: Request context
        :param image_id: The opaque image identifier
        :param user_id: Request user id
        :param project_id: Request project id
        :param location: Image location to handling

        :retval a boolean value to inform handling success or not
        """
        pass

    @abc.abstractmethod
    def _move_image(self, src_path, dst_path,
                    context=None, image_id=None, user_id=None, project_id=None,
                    location=None):
        """Move an image on local.
        Specific handler can using particular approach to
        implement this method which base on '_fetch_image()' implementation.

        :param src_path: The image object source path
        :param dst_path: The image object destination path
        :param context: Request context
        :param image_id: The opaque image identifier
        :param user_id: Request user id
        :param project_id: Request project id
        :param location: Image location to handling

        :retval a boolean value to inform handling success or not
        """
        pass

    def _associate(self, path, location):
        if sys.version_info >= (3, 0, 0):
            _basestring = str
        else:
            _basestring = basestring

        if path is None:
            return
        elif not isinstance(path, _basestring):
            return
        elif len(path.strip()) == 0:
            return

        try:
            self.associate_fn(self, path.strip(), location)
        except Exception:
            LOG.warn(_("Failed to call image handler association hook."))

    def _disassociate(self, path):
        try:
            self.disassociate_fn(self, path)
        except Exception:
            LOG.warn(_("Failed to call image handler disassociation hook."))
