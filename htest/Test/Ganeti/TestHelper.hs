{-# LANGUAGE TemplateHaskell #-}

{-| Unittest helpers for Haskell components

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

module Test.Ganeti.TestHelper
  ( testSuite
  , genArbitrary
  ) where

import Control.Applicative
import Data.List (stripPrefix, isPrefixOf)
import Data.Maybe (fromMaybe)
import Test.Framework
import Test.Framework.Providers.HUnit
import Test.Framework.Providers.QuickCheck2
import Test.HUnit (Assertion)
import Test.QuickCheck
import Language.Haskell.TH

-- | Test property prefix.
propPrefix :: String
propPrefix = "prop_"

-- | Test case prefix.
casePrefix :: String
casePrefix = "case_"

-- | Tries to drop a prefix from a string.
simplifyName :: String -> String -> String
simplifyName pfx string = fromMaybe string (stripPrefix pfx string)

-- | Builds a test from a QuickCheck property.
runProp :: Testable prop => String -> prop -> Test
runProp = testProperty . simplifyName propPrefix

-- | Builds a test for a HUnit test case.
runCase :: String -> Assertion -> Test
runCase = testCase . simplifyName casePrefix

-- | Runs the correct test provider for a given test, based on its
-- name (not very nice, but...).
run :: Name -> Q Exp
run name =
  let str = nameBase name
      nameE = varE name
      strE = litE (StringL str)
  in case () of
       _ | propPrefix `isPrefixOf` str -> [| runProp $strE $nameE |]
         | casePrefix `isPrefixOf` str -> [| runCase $strE $nameE |]
         | otherwise -> fail $ "Unsupported test function name '" ++ str ++ "'"

-- | Convert slashes in a name to underscores.
mapSlashes :: String -> String
mapSlashes = map (\c -> if c == '/' then '_' else c)

-- | Builds a test suite.
testSuite :: String -> [Name] -> Q [Dec]
testSuite tsname tdef = do
  let fullname = mkName $ "test" ++ mapSlashes tsname
  tests <- mapM run tdef
  sigtype <- [t| (String, [Test]) |]
  return [ SigD fullname sigtype
         , ValD (VarP fullname) (NormalB (TupE [LitE (StringL tsname),
                                                ListE tests])) []
         ]

-- | Builds an arbitrary value for a given constructor. This doesn't
-- use the actual types of the fields, since we expect arbitrary
-- instances for all of the types anyway, we only care about the
-- number of fields.
mkConsArbitrary :: (Name, [a]) -> Exp
mkConsArbitrary (name, types) =
  let infix_arb a = InfixE (Just a) (VarE '(<*>)) (Just (VarE 'arbitrary))
      constr = AppE (VarE 'pure) (ConE name)
  in foldl (\a _ -> infix_arb a) constr types

-- | Extracts the name and the types from a constructor.
conInfo :: Con -> (Name, [Type])
conInfo (NormalC name t)     = (name, map snd t)
conInfo (RecC    name t)     = (name, map (\(_, _, x) -> x) t)
conInfo (InfixC t1 name t2)  = (name, [snd t1, snd t2])
conInfo (ForallC _ _ subcon) = conInfo subcon

-- | Builds an arbitrary instance for a regular data type (i.e. not Bounded).
mkRegularArbitrary :: Name -> [Con] -> Q [Dec]
mkRegularArbitrary name cons = do
  expr <- case cons of
            [] -> fail "Can't make Arbitrary instance for an empty data type"
            [x] -> return $ mkConsArbitrary (conInfo x)
            xs -> appE (varE 'oneof) $
                  listE (map (return . mkConsArbitrary . conInfo) xs)
  return [InstanceD [] (AppT (ConT ''Arbitrary) (ConT name))
          [ValD (VarP 'arbitrary) (NormalB expr) []]]

-- | Builds a default Arbitrary instance for a type. This requires
-- that all members are of types that already have Arbitrary
-- instances, and that the arbitrary instances are well behaved
-- (w.r.t. recursive data structures, or similar concerns). In that
-- sense, this is not appropriate for all data types, just those that
-- are simple but very repetitive or have many simple fields.
genArbitrary :: Name -> Q [Dec]
genArbitrary name = do
  r <- reify name
  case r of
    TyConI (DataD _ _ _ cons _) ->
      mkRegularArbitrary name cons
    TyConI (NewtypeD _ _ _ con _) ->
      mkRegularArbitrary name [con]
    TyConI (TySynD _ _ (ConT tn)) -> genArbitrary tn
    _ -> fail $ "Invalid type in call to genArbitrary for " ++ show name
         ++ ", type " ++ show r
