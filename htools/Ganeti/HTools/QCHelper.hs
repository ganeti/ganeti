{-# LANGUAGE TemplateHaskell #-}

{-| Unittest helpers for ganeti-htools

-}

{-

Copyright (C) 2011 Google Inc.

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

import Test.QuickCheck
import Language.Haskell.TH

run :: Testable prop => prop -> Args -> IO Result
run = flip quickCheckWithResult

testSuite :: String -> [Name] -> Q [Dec]
testSuite tsname tdef = do
  let fullname = mkName $ "test" ++ tsname
  tests <- mapM (\n -> [| (run $(varE n), $(litE . StringL . nameBase $ n)) |])
           tdef
  sigtype <- [t| (String, [(Args -> IO Result, String)]) |]
  return [ SigD fullname sigtype
         , ValD (VarP fullname) (NormalB (TupE [LitE (StringL tsname),
                                                ListE tests])) []
         ]
