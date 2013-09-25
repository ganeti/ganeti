{-| Template Haskell code for Haskell to Python constants.

-}

{-

Copyright (C) 2013 Google Inc.

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
{-# LANGUAGE TemplateHaskell #-}
module Ganeti.Hs2Py.GenConstants (genPyConstants) where

import Language.Haskell.TH

import Ganeti.THH

fileFromModule :: Maybe String -> String
fileFromModule Nothing = ""
fileFromModule (Just name) = "src/" ++ map dotToSlash name ++ ".hs"
  where dotToSlash '.' = '/'
        dotToSlash c = c

comment :: Name -> String
comment name =
  "# Generated automatically from Haskell constant '" ++ nameBase name ++
  "' in file '" ++ fileFromModule (nameModule name) ++ "'"

genList :: Name -> [Name] -> Q [Dec]
genList name consNames = do
  let cons = listE $ map (\n -> tupE [mkString n, mkPyValueEx n]) consNames
  sig <- sigD name [t| [(String, String)] |]
  fun <- funD name [clause [] (normalB cons) []]
  return [sig, fun]
  where mkString n = stringE (comment n ++ "\n" ++ deCamelCase (nameBase n))
        mkPyValueEx n = [| showValue $(varE n) |]

genPyConstants :: String -> [Name] -> Q [Dec]
genPyConstants name = genList (mkName name)
