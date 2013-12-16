{-# LANGUAGE TemplateHaskell #-}

{-| Combines the construction of RPC server components and their Python stubs.

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

module Ganeti.THH.PyRPC
  ( genPyUDSRpcStub
  , genPyUDSRpcStubStr
  ) where

import Control.Monad
import Data.Char (toLower, toUpper)
import Data.Functor
import Data.Maybe (fromMaybe)
import Language.Haskell.TH
import Language.Haskell.TH.Syntax (liftString)
import Text.PrettyPrint

import Ganeti.THH.Types

-- | The indentation step in generated Python files.
pythonIndentStep :: Int
pythonIndentStep = 2

-- | A helper function that nests a block of generated output by the default
-- step (see 'pythonIndentStep').
nest' :: Doc -> Doc
nest' = nest pythonIndentStep

-- | The name of an abstract function to which all method in a Python stub
-- are forwarded to.
genericInvokeName :: String
genericInvokeName = "_GenericInvoke"

-- | The name of a function that returns the socket path for reaching the
-- appropriate RPC client.
socketPathName :: String
socketPathName = "_GetSocketPath"

-- | Create a Python expression that applies a given function to a list of
-- given expressions
apply :: String -> [Doc] -> Doc
apply name as = text name <> parens (hcat $ punctuate (text ", ") as)

-- | An empty line block.
emptyLine :: Doc
emptyLine = text "" -- apparently using 'empty' doesn't work

lowerFirst :: String -> String
lowerFirst (x:xs) = toLower x : xs
lowerFirst []     = []

upperFirst :: String -> String
upperFirst (x:xs) = toUpper x : xs
upperFirst []     = []

-- | Creates a method declaration given a function name and a list of
-- Haskell types corresponding to its arguments.
toFunc :: String -> [Type] -> Q Doc
toFunc fname as = do
    args <- zipWithM varName [1..] as
    let args' = text "self" : args
        callName = lowerFirst fname
    return $ (text "def" <+> apply fname args') <> colon $+$
             nest' (text "return" <+>
                    text "self." <>
                    apply genericInvokeName (text (show callName) : args)
             )
  where
    -- | Create a name for a method argument, given its index position
    -- and Haskell type.
    varName :: Int -> Type -> Q Doc
    varName _   (VarT n)              = lowerFirstNameQ n
    varName _   (ConT n)              = lowerFirstNameQ n
    varName idx (AppT ListT t)        = listOf idx t
    varName idx (AppT (ConT n) t)
      | n == ''[]                     = listOf idx t
    varName idx t                     = do
      report False $ "Don't know how to make a Python variable name from "
                     ++ show t ++ "; using a numbered one."
      return $ text ('_' : show idx)

    -- | Create a name for a method argument, knowing that its a list of
    -- a given type.
    listOf :: Int -> Type -> Q Doc
    listOf idx t = (<> text "List") <$> varName idx t

    lowerFirstNameQ :: Name -> Q Doc
    lowerFirstNameQ = return . text . lowerFirst . nameBase

-- | Creates a method declaration by inspecting (reifying) Haskell's function
-- name.
nameToFunc :: Name -> Q Doc
nameToFunc name = do
    (as, _) <- funArgs `liftM` typeOfFun name
    -- If the function has just one argument, try if it isn't a tuple;
    -- if not, use the arguments as they are.
    let as' = fromMaybe as $ case as of
                                [t] -> tupleArgs t -- TODO CHECK!
                                _   -> Nothing
    toFunc (upperFirst $ nameBase name) as'

-- | Generates a Python class stub, given a class name, the list of Haskell
-- functions to expose as methods, and a optionally a piece of code to
-- include.
namesToClass
  :: String       -- ^ the class name
  -> Doc          -- ^ Python code to include in the class
  -> [Name]       -- ^ the list of functions to include
  -> Q Doc
namesToClass cname pycode fns = do
  fnsCode <- mapM (liftM ($+$ emptyLine) . nameToFunc) fns
  return $ vcat [ text "class" <+> apply cname [text "object"] <> colon
                , nest' (
                    pycode $+$ vcat fnsCode
                  )
                ]

-- | Takes a list of function names and creates a RPC handler that delegates
-- calls to them, as well as writes out the corresponding Python stub.
--
-- See 'mkRpcM' for the requirements on the passed functions and the returned
-- expression.
genPyUDSRpcStub
  :: String     -- ^ the name of the class to be generated
  -> String     -- ^ the name of the constant from @constants.py@ holding
                --   the path to a UDS socket
  -> [Name]     -- ^ names of functions to include
  -> Q Doc
genPyUDSRpcStub className constName = liftM (header $+$) .
                                      namesToClass className stubCode
  where
    header = text "# This file is automatically generated, do not edit!" $+$
             text "# pylint: disable-all"
    stubCode =
      abstrMethod genericInvokeName [ text "method", text "*args"] $+$
      method socketPathName [] (
         text "from ganeti import pathutils" $+$
         text "return" <+> text "pathutils." <> text constName)
    method name args body =
      text "def" <+> apply name (text "self" : args) <> colon $+$
      nest' body $+$
      emptyLine
    abstrMethod name args = method name args $
      text "raise" <+> apply "NotImplementedError" []

-- The same as 'genPyUDSRpcStub', but returns the result as a @String@
-- expression.
genPyUDSRpcStubStr
  :: String   -- ^ the name of the class to be generated
  -> String   -- ^ the constant in @pathutils.py@ holding the socket path
  -> [Name]   -- ^ functions to include
  -> Q Exp
genPyUDSRpcStubStr className constName names =
    liftString . render =<< genPyUDSRpcStub className constName names
