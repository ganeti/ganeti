{-# LANGUAGE TemplateHaskell, QuasiQuotes #-}

{-| TemplateHaskell helper for HTools.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

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

module Ganeti.THH ( declareSADT
                  , makeJSONInstance
                  , genOpID
                  ) where

import Control.Monad (liftM)
import Data.Char
import Data.List
import Language.Haskell.TH

import qualified Text.JSON as JSON

-- | Ensure first letter is lowercase.
--
-- Used to convert type name to function prefix, e.g. in @data Aa ->
-- aaToString@.
ensureLower :: String -> String
ensureLower [] = []
ensureLower (x:xs) = toLower x:xs

-- | ToString function name.
toStrName :: String -> Name
toStrName = mkName . (++ "ToString") . ensureLower

-- | FromString function name.
fromStrName :: String -> Name
fromStrName = mkName . (++ "FromString") . ensureLower

-- | Converts a name to it's varE/litE representations.
--
reprE :: Either String Name -> Q Exp
reprE (Left name) = litE (StringL name)
reprE (Right name) = varE name

-- | Generates a data type declaration.
--
-- The type will have a fixed list of instances.
strADTDecl :: Name -> [String] -> Dec
strADTDecl name constructors =
    DataD [] name []
              (map (flip NormalC [] . mkName) constructors)
              [''Show, ''Read, ''Eq, ''Enum, ''Bounded, ''Ord]

-- | Generates a toString function.
--
-- This generates a simple function of the form:
--
-- @
-- nameToString :: Name -> String
-- nameToString Cons1 = var1
-- nameToString Cons2 = \"value2\"
-- @
genToString :: Name -> Name -> [(String, Either String Name)] -> Q [Dec]
genToString fname tname constructors = do
  sigt <- [t| $(conT tname) -> String |]
  -- the body clauses, matching on the constructor and returning the
  -- string value
  clauses <- mapM  (\(c, v) -> clause [recP (mkName c) []]
                             (normalB (reprE v)) []) constructors
  return [SigD fname sigt, FunD fname clauses]

-- | Generates a fromString function.
--
-- The function generated is monadic and can fail parsing the
-- string. It is of the form:
--
-- @
-- nameFromString :: (Monad m) => String -> m Name
-- nameFromString s | s == var1       = Cons1
--                  | s == \"value2\" = Cons2
--                  | otherwise = fail /.../
-- @
genFromString :: Name -> Name -> [(String, Name)] -> Q [Dec]
genFromString fname tname constructors = do
  -- signature of form (Monad m) => String -> m $name
  sigt <- [t| (Monad m) => String -> m $(conT tname) |]
  -- clauses for a guarded pattern
  let varp = mkName "s"
      varpe = varE varp
  clauses <- mapM (\(c, v) -> do
                     -- the clause match condition
                     g <- normalG [| $varpe == $(varE v) |]
                     -- the clause result
                     r <- [| return $(conE (mkName c)) |]
                     return (g, r)) constructors
  -- the otherwise clause (fallback)
  oth_clause <- do
    g <- normalG [| otherwise |]
    r <- [|fail ("Invalid string value for type " ++
                 $(litE (stringL (nameBase tname))) ++ ": " ++ $varpe) |]
    return (g, r)
  let fun = FunD fname [Clause [VarP varp]
                        (GuardedB (clauses++[oth_clause])) []]
  return [SigD fname sigt, fun]

-- | Generates a data type from a given string format.
--
-- The format is expected to multiline. The first line contains the
-- type name, and the rest of the lines must contain two words: the
-- constructor name and then the string representation of the
-- respective constructor.
--
-- The function will generate the data type declaration, and then two
-- functions:
--
-- * /name/ToString, which converts the type to a string
--
-- * /name/FromString, which (monadically) converts from a string to the type
--
-- Note that this is basically just a custom show/read instance,
-- nothing else.
declareSADT :: String -> [(String, Name)] -> Q [Dec]
declareSADT sname cons = do
  let name = mkName sname
      ddecl = strADTDecl name (map fst cons)
      -- process cons in the format expected by genToString
      cons' = map (\(a, b) -> (a, Right b)) cons
  tostr <- genToString (toStrName sname) name cons'
  fromstr <- genFromString (fromStrName sname) name cons
  return $ ddecl:tostr ++ fromstr


-- | Creates the showJSON member of a JSON instance declaration.
--
-- This will create what is the equivalent of:
--
-- @
-- showJSON = showJSON . /name/ToString
-- @
--
-- in an instance JSON /name/ declaration
genShowJSON :: String -> Q [Dec]
genShowJSON name = [d| showJSON = JSON.showJSON . $(varE (toStrName name)) |]

-- | Creates the readJSON member of a JSON instance declaration.
--
-- This will create what is the equivalent of:
--
-- @
-- readJSON s = case readJSON s of
--                Ok s' -> /name/FromString s'
--                Error e -> Error /description/
-- @
--
-- in an instance JSON /name/ declaration
genReadJSON :: String -> Q Dec
genReadJSON name = do
  let s = mkName "s"
  body <- [| case JSON.readJSON $(varE s) of
               JSON.Ok s' -> $(varE (fromStrName name)) s'
               JSON.Error e ->
                   JSON.Error $ "Can't parse string value for type " ++
                           $(litE (StringL name)) ++ ": " ++ e
           |]
  return $ FunD (mkName "readJSON") [Clause [VarP s] (NormalB body) []]

-- | Generates a JSON instance for a given type.
--
-- This assumes that the /name/ToString and /name/FromString functions
-- have been defined as by the 'declareSADT' function.
makeJSONInstance :: Name -> Q [Dec]
makeJSONInstance name = do
  let base = nameBase name
  showJ <- genShowJSON base
  readJ <- genReadJSON base
  return [InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name)) (readJ:showJ)]

-- | Transforms a CamelCase string into an_underscore_based_one.
deCamelCase :: String -> String
deCamelCase =
    intercalate "_" . map (map toUpper) . groupBy (\_ b -> not $ isUpper b)

-- | Computes the name of a given constructor
constructorName :: Con -> Q Name
constructorName (NormalC name _) = return name
constructorName (RecC name _)    = return name
constructorName x                = fail $ "Unhandled constructor " ++ show x

-- | Builds the constructor-to-string function.
--
-- This generates a simple function of the following form:
--
-- @
-- fname (ConStructorOne {}) = "CON_STRUCTOR_ONE"
-- fname (ConStructorTwo {}) = "CON_STRUCTOR_TWO"
-- @
--
-- This builds a custom list of name/string pairs and then uses
-- 'genToString' to actually generate the function
genOpID :: Name -> String -> Q [Dec]
genOpID name fname = do
  TyConI (DataD _ _ _ cons _) <- reify name
  cnames <- mapM (liftM nameBase . constructorName) cons
  let svalues = map (Left . deCamelCase) cnames
  genToString (mkName fname) name $ zip cnames svalues
