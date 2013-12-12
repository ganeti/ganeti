{-# LANGUAGE TemplateHaskell #-}

{-| PyType helper for Ganeti Haskell code.

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
