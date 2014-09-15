{-| Template Haskell code for Haskell to Python constants.

-}

{-

Copyright (C) 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
