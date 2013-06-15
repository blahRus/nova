#    Copyright 2013 IBM Corp.
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

import stevedore

from nova import context
from nova import exception
from nova import test
from nova.tests.image import fake as fake_image
from nova.virt import imagehandler
from nova.virt.imagehandler import default as default_imagehandler


class ImageHandlerTestCase(test.TestCase):
    class FakeLibvirtDriver(object):
        pass

    def setUp(self):
        super(ImageHandlerTestCase, self).setUp()
        self.context = context.get_admin_context()
        fake_image.stub_out_image_service(self.stubs)
        imagehandler._IMAGE_HANDLERS = []
        imagehandler._IMAGE_HANDLERS_ASSO = {}

    def tearDown(self):
        fake_image.FakeImageService_reset()
        super(ImageHandlerTestCase, self).tearDown()

    def test_match_locations_empty(self):
        matched = imagehandler._match_locations([], ())
        self.assertEqual(matched, [])
        matched = imagehandler._match_locations(None, ())
        self.assertEqual(matched, [])
        matched = imagehandler._match_locations([], None)
        self.assertEqual(matched, [])

    def test_match_locations_location_dependent(self):
        fake_locations = [{'url': 'fake1://url', 'metadata': {}},
                          {'url': 'fake2://url', 'metadata': {}}]
        matched = imagehandler._match_locations(fake_locations, ('fake1'))
        self.assertEqual(matched, [{'url': 'fake1://url', 'metadata': {}}])
        matched = imagehandler._match_locations(fake_locations,
                                                ('no_existing'))
        self.assertEqual(matched, [])

    def test_match_locations_location_independent(self):
        fake_locations = [{'url': 'fake1://url', 'metadata': {}},
                          {'url': 'fake2://url', 'metadata': {}}]
        matched = imagehandler._match_locations(fake_locations, ())
        self.assertEqual(matched, fake_locations)

    def test_image_handler_assoation_hooks(self):
        handler = 'fake_handler'
        path = 'fake/image/path'
        location = 'fake://image_location_url'
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)
        imagehandler._image_handler_asso(handler, path, location)
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 1)
        self.assertIn(path, imagehandler._IMAGE_HANDLERS_ASSO)
        self.assertEqual(imagehandler._IMAGE_HANDLERS_ASSO[path],
                         (handler, location))
        imagehandler._image_handler_disasso('another_handler',
                                            'another/fake/image/path')
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 1)
        imagehandler._image_handler_disasso(handler, path)
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)

    def test_load_image_handlers(self):
        self.flags(image_handlers=['default'])
        imagehandler.load_image_handlers(self.FakeLibvirtDriver())
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS), 1)
        self.assertTrue(isinstance(imagehandler._IMAGE_HANDLERS[0],
                                   default_imagehandler.DefaultImageHandler))
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)

    def test_load_image_handlers_with_invalid_handler_name(self):
        self.flags(image_handlers=['invaild1', 'default', 'invaild2'])
        imagehandler.load_image_handlers(self.FakeLibvirtDriver())
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS), 1)
        self.assertTrue(isinstance(imagehandler._IMAGE_HANDLERS[0],
                                   default_imagehandler.DefaultImageHandler))
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)

    def test_load_image_handlers_with_deduplicating(self):
        handlers = ['handler1', 'handler2', 'handler3']

        def _fake_stevedore_extension_manager(*args, **kwargs):
            ret = lambda: None
            ret.names = lambda: handlers
            return ret

        def _fake_stevedore_driver_manager(*args, **kwargs):
            ret = lambda: None
            ret.driver = kwargs['name']
            return ret

        self.stub = self.stubs.Set(stevedore.extension, "ExtensionManager",
                                   _fake_stevedore_extension_manager)
        self.stub = self.stubs.Set(stevedore.driver, "DriverManager",
                                   _fake_stevedore_driver_manager)

        self.flags(image_handlers=['invaild1', 'handler1  ', '  handler3',
                                   'invaild2', '  handler2  '])
        imagehandler.load_image_handlers(self.FakeLibvirtDriver())
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS), 3)
        for handler in imagehandler._IMAGE_HANDLERS:
            self.assertTrue(handler in handlers)
        self.assertEqual(imagehandler._IMAGE_HANDLERS,
                         ['handler1', 'handler3', 'handler2'])
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)

    def test_load_image_handlers_with_load_handler_failure(self):
        handlers = ['raise_exception', 'default']

        def _fake_stevedore_extension_manager(*args, **kwargs):
            ret = lambda: None
            ret.names = lambda: handlers
            return ret

        def _fake_stevedore_driver_manager(*args, **kwargs):
            if kwargs['name'] == 'raise_exception':
                raise Exception('handler failed to initialize.')
            else:
                ret = lambda: None
                ret.driver = kwargs['name']
                return ret

        self.stub = self.stubs.Set(stevedore.extension, "ExtensionManager",
                                   _fake_stevedore_extension_manager)
        self.stub = self.stubs.Set(stevedore.driver, "DriverManager",
                                   _fake_stevedore_driver_manager)

        self.flags(image_handlers=['raise_exception', 'default',
                                   'raise_exception', 'default'])
        imagehandler.load_image_handlers(self.FakeLibvirtDriver())
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS), 1)
        self.assertEqual(imagehandler._IMAGE_HANDLERS, ['default'])
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)

    def _handle_image_without_associated_handle(self, image_id,
                                                expected_locations,
                                                expected_handled_location,
                                                expected_handled_path):
        def fake_handler_fetch(self, context, image_id, path,
                               user_id=None, project_id=None, location=None):
            return location == expected_handled_location

        self.stubs.Set(default_imagehandler.DefaultImageHandler,
                       '_fetch_image', fake_handler_fetch)

        self.flags(image_handlers=['default'])
        imagehandler.load_image_handlers(self.FakeLibvirtDriver())
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS), 1)
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 0)

        check_left_loc_count = expected_handled_location in expected_locations
        if check_left_loc_count:
            unused_location_count = (len(expected_locations) -
                 expected_locations.index(expected_handled_location) - 1)

        self._fetch_image(image_id, expected_locations, expected_handled_path)

        if check_left_loc_count:
            self.assertEqual(unused_location_count, len(expected_locations))
        self.assertEqual(len(imagehandler._IMAGE_HANDLERS_ASSO), 1)
        self.assertEqual(
             imagehandler._IMAGE_HANDLERS_ASSO[expected_handled_path],
             (imagehandler._IMAGE_HANDLERS[0], expected_handled_location))

    def _fetch_image(self, image_id, expected_locations,
                     expected_handled_path):
        for (handler, loc) in imagehandler.handle_image(self.context,
                                image_id, target_path=expected_handled_path):
            self.assertEqual(imagehandler._IMAGE_HANDLERS[0], handler)
            if (len(expected_locations) > 0):
                self.assertEqual(expected_locations.pop(0), loc)
            handler.fetch_image(context, image_id, expected_handled_path,
                                location=loc)

    def test_handle_image_without_associated_handle(self):
        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        # Image will be handled successful on second location.
        expected_handled_location = 'fake_location2'
        expected_handled_path = 'fake/image/path2'
        self._handle_image_without_associated_handle(image_id,
                                                     expected_locations,
                                                     expected_handled_location,
                                                     expected_handled_path)

    def test_handle_image_with_associated_handler(self):
        self.get_locations_called = False

        def fake_get_locations(*args, **kwargs):
            self.get_locations_called = True

        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        expected_handled_location = 'fake_location'
        expected_handled_path = 'fake/image/path'

        # 1) Handle image without cached association information
        self._handle_image_without_associated_handle(image_id,
                                                     list(expected_locations),
                                                     expected_handled_location,
                                                     expected_handled_path)

        self.stubs.Set(fake_image._FakeImageService, 'get_locations',
                       fake_get_locations)

        # 2) Handle image with cached association information
        self._fetch_image(image_id, expected_locations, expected_handled_path)

        self.assertFalse(self.get_locations_called)
        del self.get_locations_called

    def test_handle_image_with_association_discarded(self):
        self.get_locations_called = False
        original_get_locations = fake_image._FakeImageService.get_locations

        def fake_get_locations(*args, **kwargs):
            self.get_locations_called = True
            return original_get_locations(*args, **kwargs)

        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        expected_handled_location = 'fake_location'
        expected_handled_path = 'fake/image/path'

        # 1) Handle image without cached association information
        self._handle_image_without_associated_handle(image_id,
                                                     list(expected_locations),
                                                     expected_handled_location,
                                                     expected_handled_path)

        # 2) Clear cached association information
        imagehandler._IMAGE_HANDLERS_ASSO = {}

        # 3) Handle image with discarded association information
        self.stubs.Set(fake_image._FakeImageService, 'get_locations',
                       fake_get_locations)

        self._fetch_image(image_id, expected_locations, expected_handled_path)

        self.assertTrue(self.get_locations_called)
        del self.get_locations_called

    def test_handle_image_no_handler_available(self):
        self.get_locations_called = False
        original_get_locations = fake_image._FakeImageService.get_locations

        def fake_get_locations(*args, **kwargs):
            self.get_locations_called = True
            return original_get_locations(*args, **kwargs)

        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        expected_handled_location = 'fake_location3'
        expected_handled_path = 'fake/image/path'

        self.assertRaises(exception.NoImageHandlerAvailable,
                          self._handle_image_without_associated_handle,
                          image_id,
                          expected_locations,
                          expected_handled_location,
                          expected_handled_path)
