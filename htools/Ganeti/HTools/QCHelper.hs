{-# LANGUAGE TemplateHaskell #-}

{-| Unittest helpers for ganeti-htools

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

module Ganeti.HTools.QCHelper
  ( testSuite
  ) where

import Data.List (stripPrefix)
import Data.Maybe (fromMaybe)
import Test.QuickCheck
import Test.Framework
import Test.Framework.Providers.QuickCheck2
import Language.Haskell.TH

-- | Tries to drop a prefix from a string.
simplifyName :: String -> String -> String
simplifyName pfx string = fromMaybe string (stripPrefix pfx string)

-- | Builds a test from a property and given arguments.
run :: Testable prop => String -> String -> prop -> Test
run pfx name = testProperty (simplifyName ("prop_" ++ pfx ++ "_") name)

-- | Builds a test suite.
testSuite :: String -> [Name] -> Q [Dec]
testSuite tsname tdef = do
  let fullname = mkName $ "test" ++ tsname
  tests <- mapM (\n -> [| run tsname
                          $(litE . StringL . nameBase $ n) $(varE n) |])
           tdef
  sigtype <- [t| (String, [Test]) |]
  return [ SigD fullname sigtype
         , ValD (VarP fullname) (NormalB (TupE [LitE (StringL tsname),
                                                ListE tests])) []
         ]
