{-# LANGUAGE TemplateHaskell #-}

{-| PyType helper for Ganeti Haskell code.

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
module Ganeti.THH.PyType
  ( PyType(..)
  , pyType
  , pyOptionalType
  ) where

import Control.Applicative
import Control.Monad
import Data.List (intercalate)
import Language.Haskell.TH
import Language.Haskell.TH.Syntax (Lift(..))

import Ganeti.PyValue


-- | Represents a Python encoding of types.
data PyType
    = PTMaybe PyType
    | PTApp PyType [PyType]
    | PTOther String
    | PTAny
    | PTDictOf
    | PTListOf
    | PTNone
    | PTObject
    | PTOr
    | PTSetOf
    | PTTupleOf
  deriving (Show, Eq, Ord)

-- TODO: We could use th-lift to generate this instance automatically.
instance Lift PyType where
  lift (PTMaybe x)   = [| PTMaybe x |]
  lift (PTApp tf as) = [| PTApp tf as |]
  lift (PTOther i)   = [| PTOther i |]
  lift PTAny         = [| PTAny |]
  lift PTDictOf      = [| PTDictOf |]
  lift PTListOf      = [| PTListOf |]
  lift PTNone        = [| PTNone |]
  lift PTObject      = [| PTObject |]
  lift PTOr          = [| PTOr |]
  lift PTSetOf       = [| PTSetOf |]
  lift PTTupleOf     = [| PTTupleOf |]

instance PyValue PyType where
  -- Use lib/ht.py type aliases to avoid Python creating redundant
  -- new match functions for commonly used OpCode param types.
  showValue (PTMaybe (PTOther "NonEmptyString")) = ht "MaybeString"
  showValue (PTMaybe (PTOther "Bool")) = ht "MaybeBool"
  showValue (PTMaybe PTDictOf) = ht "MaybeDict"
  showValue (PTMaybe PTListOf) = ht "MaybeList"

  showValue (PTMaybe x)   = ptApp (ht "Maybe") [x]
  showValue (PTApp tf as) = ptApp (showValue tf) as
  showValue (PTOther i)   = ht i
  showValue PTAny         = ht "Any"
  showValue PTDictOf      = ht "DictOf"
  showValue PTListOf      = ht "ListOf"
  showValue PTNone        = ht "None"
  showValue PTObject      = ht "Object"
  showValue PTOr          = ht "Or"
  showValue PTSetOf       = ht "SetOf"
  showValue PTTupleOf     = ht "TupleOf"

ht :: String -> String
ht = ("ht.T" ++)

ptApp :: String -> [PyType] -> String
ptApp name ts = name ++ "(" ++ intercalate ", " (map showValue ts) ++ ")"

-- | Converts a Haskell type name into a Python type name.
pyTypeName :: Name -> PyType
pyTypeName name =
  case nameBase name of
                "()"                -> PTNone
                "Map"               -> PTDictOf
                "Set"               -> PTSetOf
                "ListSet"           -> PTSetOf
                "Either"            -> PTOr
                "GenericContainer"  -> PTDictOf
                "JSValue"           -> PTAny
                "JSObject"          -> PTObject
                str                 -> PTOther str

-- | Converts a Haskell type into a Python type.
pyType :: Type -> Q PyType
pyType t | not (null args)  = PTApp `liftM` pyType fn `ap` mapM pyType args
  where (fn, args) = pyAppType t
pyType (ConT name)          = return $ pyTypeName name
pyType ListT                = return PTListOf
pyType (TupleT 0)           = return PTNone
pyType (TupleT _)           = return PTTupleOf
pyType typ                  = fail $ "unhandled case for type " ++ show typ

-- | Returns a type and its type arguments.
pyAppType :: Type -> (Type, [Type])
pyAppType = g []
  where
    g as (AppT typ1 typ2) = g (typ2 : as) typ1
    g as typ              = (typ, as)

-- | @pyType opt typ@ converts Haskell type @typ@ into a Python type,
-- where @opt@ determines if the converted type is optional (i.e.,
-- Maybe).
pyOptionalType :: Bool -> Type -> Q PyType
pyOptionalType True  typ = PTMaybe <$> pyType typ
pyOptionalType False typ = pyType typ
