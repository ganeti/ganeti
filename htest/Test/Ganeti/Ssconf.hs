{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for ganeti-htools.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Test.Ganeti.Ssconf (testSsconf) where

import Test.QuickCheck

import Data.List

import Test.Ganeti.TestHelper

import qualified Ganeti.Ssconf as Ssconf

-- * Ssconf tests

instance Arbitrary Ssconf.SSKey where
  arbitrary = elements [minBound..maxBound]

prop_filename :: Ssconf.SSKey -> Property
prop_filename key =
  printTestCase "Key doesn't start with correct prefix" $
    Ssconf.sSFilePrefix `isPrefixOf` Ssconf.keyToFilename (Just "") key

testSuite "Ssconf"
  [ 'prop_filename
  ]
