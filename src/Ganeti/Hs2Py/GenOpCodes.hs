{-| GenOpCodes handles Python opcode generation.

GenOpCodes contains the helper functions that generate the Python
opcodes as strings from the Haskell opcode description.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.
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

module Ganeti.Hs2Py.GenOpCodes (showPyClasses) where

import Data.List (intercalate)

import Ganeti.OpCodes
import Ganeti.THH

-- | Generates the Python class docstring.
pyClassDoc :: String -> String
pyClassDoc doc
  | length (lines doc) > 1 =
    "  \"\"\"" ++ doc ++ "\n\n" ++ "  \"\"\"" ++ "\n"
  | otherwise =
    "  \"\"\"" ++ doc ++ "\"\"\"" ++ "\n"

-- | Generates an opcode parameter in Python.
pyClassField :: OpCodeField -> String
pyClassField (OpCodeField name typ Nothing doc) =
  "(" ++ intercalate ", " [show name, "None", showValue typ, show doc] ++ ")"
pyClassField (OpCodeField name typ (Just def) doc) =
  "(" ++ intercalate ", "
           [show name, showValue def, showValue typ, show doc] ++ ")"

-- | Comma intercalates and indents opcode parameters in Python.
intercalateIndent :: [String] -> String
intercalateIndent xs = intercalate "," (map ("\n    " ++) xs)

-- | Generates an opcode as a Python class.
showPyClass :: OpCodeDescriptor -> String
showPyClass (OpCodeDescriptor name typ doc fields dsc) =
  let
    baseclass
      | name == "OpInstanceMultiAlloc" = "OpInstanceMultiAllocBase"
      | otherwise = "OpCode"
    opDscField
      | null dsc = ""
      | otherwise = "  OP_DSC_FIELD = " ++ show dsc ++ "\n"
    withLU
      | name == "OpTestDummy" = "\n  WITH_LU = False"
      | otherwise = ""
  in
   "class " ++ name ++ "(" ++ baseclass ++ "):" ++ "\n" ++
   pyClassDoc doc ++
   opDscField ++
   "  OP_PARAMS = [" ++
   intercalateIndent (map pyClassField fields) ++
   "\n    ]" ++ "\n" ++
   "  OP_RESULT = " ++ showValue typ ++
   withLU ++ "\n\n"

-- | Generates all opcodes as Python classes.
showPyClasses :: String
showPyClasses = concatMap showPyClass pyClasses
