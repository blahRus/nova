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
Default image handler implementation.
"""

import os

from nova.image import glance
from nova.openstack.common import fileutils
from nova.virt.imagehandler import base


class DefaultImageHandler(base.ImageHandler):
    """Default image handler class.

    Using downloading method to fetch image and save to regular file,
    and use os.unlink to remove image, those like Nova default behavior.
    """
    def __init__(self, driver=None, *args, **kwargs):
        super(DefaultImageHandler, self).__init__(driver, *args, **kwargs)

    def get_schemes(self):
        # Note(zhiyan): empty set meaning handler have not scheme limitation.
        return ()

    def _fetch_image(self, context, image_id, path,
                     user_id=None, project_id=None, location=None):
        # TODO(vish): Improve context handling and add owner and auth data
        #             when it is added to glance.  Right now there is no
        #             auth checking in glance, so we assume that access was
        #             checked before we got here.
        (image_service, image_id) = glance.get_remote_image_service(context,
                                                                    image_id)
        with fileutils.remove_path_on_error(path):
            image_service.download(context, image_id, dst_path=path)
        return os.path.exists(path)

    def _remove_image(self, path,
                      context=None, image_id=None,
                      user_id=None, project_id=None,
                      location=None):
        fileutils.delete_if_exists(path)
        return not os.path.exists(path)

    def _move_image(self, src_path, dst_path,
                    context=None, image_id=None, user_id=None, project_id=None,
                    location=None):
        os.rename(src_path, dst_path)
        return os.path.exists(dst_path) and not os.path.exists(src_path)
