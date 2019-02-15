{-# LANGUAGE TemplateHaskell #-}

{-| Unittest helpers for TemplateHaskell components.

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

-- | Test case prefix without underscore.
case2Pfx :: String
case2Pfx = "case"

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
         | case2Pfx `isPrefixOf` str ->
           [| (testCase . simplifyName case2Pfx) $strE $nameE |]
         | otherwise -> fail $ "Unsupported test function name '" ++ str ++ "'"

-- | Convert slashes in a name to underscores.
mapSlashes :: String -> String
mapSlashes = map (\c -> if c == '/' then '_' else c)

-- | Builds a test suite.
testSuite :: String -> [Name] -> Q [Dec]
testSuite tsname tdef = do
  let fullname = mkName $ "test" ++ mapSlashes tsname
  tests <- mapM run tdef
  sigtype <- [t| Test |]
  body <- [| testGroup $(litE $ stringL tsname) $(return $ ListE tests) |]
  return [ SigD fullname sigtype
         , ValD (VarP fullname) (NormalB body) []
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
