{-| GenOpCodes handles Python opcode generation.

GenOpCodes contains the helper functions that generate the Python
opcodes as strings from the Haskell opcode description.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.

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

module Ganeti.Hs2Py.GenOpCodes (showPyClasses) where

import Data.List (intercalate, zipWith4)

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
pyClassField :: String -> String -> Maybe PyValueEx -> String -> String
pyClassField name typ Nothing doc =
  "(" ++ intercalate ", " [show name, "None", typ, show doc] ++ ")"
  
pyClassField name typ (Just (PyValueEx def)) doc =
  "(" ++ intercalate ", " [show name, showValue def, typ, show doc] ++ ")"
  
-- | Comma intercalates and indents opcode parameters in Python.
intercalateIndent :: [String] -> String
intercalateIndent xs = intercalate "," (map ("\n    " ++) xs)

-- | Generates an opcode as a Python class.
showPyClass :: OpCodeDescriptor -> String
showPyClass (name, typ, doc, fields, types, defs, docs, dsc) =
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
   intercalateIndent (zipWith4 pyClassField fields types defs docs) ++
   "\n    ]" ++ "\n" ++
   "  OP_RESULT = " ++ typ ++
   withLU ++ "\n\n"

-- | Generates all opcodes as Python classes.
showPyClasses :: String
showPyClasses = concatMap showPyClass pyClasses
