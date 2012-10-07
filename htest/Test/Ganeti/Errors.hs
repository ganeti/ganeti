{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for "Ganeti.Errors".

-}

{-

Copyright (C) 2012 Google Inc.

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

module Test.Ganeti.Errors (testErrors) where

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

import qualified Ganeti.Errors as Errors

$(genArbitrary ''Errors.ErrorCode)

$(genArbitrary ''Errors.GanetiException)

-- | Tests error serialisation.
prop_GenericError_serialisation :: Errors.GanetiException -> Property
prop_GenericError_serialisation = testSerialisation

testSuite "Errors"
          [ 'prop_GenericError_serialisation
          ]
