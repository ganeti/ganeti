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

module Ganeti.THH ( Store(..)
                  , declareSADT
                  , makeJSONInstance
                  , genOpID
                  , genOpCode
                  , noDefault
                  , genStrOfOp
                  , genStrOfKey
                  , genLuxiOp
                  ) where

import Control.Monad (liftM, liftM2)
import Data.Char
import Data.List
import Language.Haskell.TH

import qualified Text.JSON as JSON

-- * Helper functions

-- | Ensure first letter is lowercase.
--
-- Used to convert type name to function prefix, e.g. in @data Aa ->
-- aaToString@.
ensureLower :: String -> String
ensureLower [] = []
ensureLower (x:xs) = toLower x:xs

-- | Helper for quoted expressions.
varNameE :: String -> Q Exp
varNameE = varE . mkName

-- | showJSON as an expression, for reuse.
showJSONE :: Q Exp
showJSONE = varNameE "showJSON"

-- | ToString function name.
toStrName :: String -> Name
toStrName = mkName . (++ "ToString") . ensureLower

-- | FromString function name.
fromStrName :: String -> Name
fromStrName = mkName . (++ "FromString") . ensureLower

-- | Converts a name to it's varE/litE representations.
--
reprE :: Either String Name -> Q Exp
reprE = either stringE varE

-- | Smarter function application.
--
-- This does simply f x, except that if is 'id', it will skip it, in
-- order to generate more readable code when using -ddump-splices.
appFn :: Exp -> Exp -> Exp
appFn f x | f == VarE 'id = x
          | otherwise = AppE f x

-- * Template code for simple string-equivalent ADTs

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
                           $(stringE name) ++ ": " ++ e
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

-- * Template code for opcodes

-- | Transforms a CamelCase string into an_underscore_based_one.
deCamelCase :: String -> String
deCamelCase =
    intercalate "_" . map (map toUpper) . groupBy (\_ b -> not $ isUpper b)

-- | Computes the name of a given constructor.
constructorName :: Con -> Q Name
constructorName (NormalC name _) = return name
constructorName (RecC name _)    = return name
constructorName x                = fail $ "Unhandled constructor " ++ show x

-- | Builds the generic constructor-to-string function.
--
-- This generates a simple function of the following form:
--
-- @
-- fname (ConStructorOne {}) = trans_fun("ConStructorOne")
-- fname (ConStructorTwo {}) = trans_fun("ConStructorTwo")
-- @
--
-- This builds a custom list of name/string pairs and then uses
-- 'genToString' to actually generate the function
genConstrToStr :: (String -> String) -> Name -> String -> Q [Dec]
genConstrToStr trans_fun name fname = do
  TyConI (DataD _ _ _ cons _) <- reify name
  cnames <- mapM (liftM nameBase . constructorName) cons
  let svalues = map (Left . trans_fun) cnames
  genToString (mkName fname) name $ zip cnames svalues

-- | Constructor-to-string for OpCode.
genOpID :: Name -> String -> Q [Dec]
genOpID = genConstrToStr deCamelCase

-- | OpCode parameter (field) type.
type OpParam = (String, Q Type, Q Exp)

-- | Generates the OpCode data type.
--
-- This takes an opcode logical definition, and builds both the
-- datatype and the JSON serialisation out of it. We can't use a
-- generic serialisation since we need to be compatible with Ganeti's
-- own, so we have a few quirks to work around.
--
-- There are three things to be defined for each parameter:
--
-- * name
--
-- * type; if this is 'Maybe', will only be serialised if it's a
--   'Just' value
--
-- * default; if missing, won't raise an exception, but will instead
--   use the default
--
genOpCode :: String                -- ^ Type name to use
          -> [(String, [OpParam])] -- ^ Constructor name and parameters
          -> Q [Dec]
genOpCode name cons = do
  decl_d <- mapM (\(cname, fields) -> do
                    -- we only need the type of the field, without Q
                    fields' <- mapM (\(_, qt, _) ->
                                         qt >>= \t -> return (NotStrict, t))
                               fields
                    return $ NormalC (mkName cname) fields')
            cons
  let declD = DataD [] (mkName name) [] decl_d [''Show, ''Read, ''Eq]

  (savesig, savefn) <- genSaveOpCode cons
  (loadsig, loadfn) <- genLoadOpCode cons
  return [declD, loadsig, loadfn, savesig, savefn]

-- | Checks whether a given parameter is options.
--
-- This requires that it's a 'Maybe'.
isOptional :: Type -> Bool
isOptional (AppT (ConT dt) _) | dt == ''Maybe = True
isOptional _ = False

-- | Generates the \"save\" expression for a single opcode parameter.
--
-- There is only one special handling mode: if the parameter is of
-- 'Maybe' type, then we only save it if it's a 'Just' value,
-- otherwise we skip it.
saveField :: Name    -- ^ The name of variable that contains the value
          -> OpParam -- ^ Parameter definition
          -> Q Exp
saveField fvar (fname, qt, _) = do
  t <- qt
  let fnexp = stringE fname
      fvare = varE fvar
  (if isOptional t
   then [| case $fvare of
             Just v' -> [( $fnexp, $showJSONE v')]
             Nothing -> []
         |]
   else [| [( $fnexp, $showJSONE $fvare )] |])

-- | Generates the \"save\" clause for an entire opcode constructor.
--
-- This matches the opcode with variables named the same as the
-- constructor fields (just so that the spliced in code looks nicer),
-- and passes those name plus the parameter definition to 'saveField'.
saveConstructor :: String    -- ^ The constructor name
                -> [OpParam] -- ^ The parameter definitions for this
                             -- constructor
                -> Q Clause  -- ^ Resulting clause
saveConstructor sname fields = do
  let cname = mkName sname
  let fnames = map (\(n, _, _) -> mkName n) fields
  let pat = conP cname (map varP fnames)
  let felems = map (uncurry saveField) (zip fnames fields)
      -- now build the OP_ID serialisation
      opid = [| [( $(stringE "OP_ID"),
                   $showJSONE $(stringE . deCamelCase $ sname) )] |]
      flist = listE (opid:felems)
      -- and finally convert all this to a json object
      flist' = [| $(varNameE "makeObj") (concat $flist) |]
  clause [pat] (normalB flist') []

-- | Generates the main save opcode function.
--
-- This builds a per-constructor match clause that contains the
-- respective constructor-serialisation code.
genSaveOpCode :: [(String, [OpParam])] -> Q (Dec, Dec)
genSaveOpCode opdefs = do
  cclauses <- mapM (uncurry saveConstructor) opdefs
  let fname = mkName "saveOpCode"
  sigt <- [t| $(conT (mkName "OpCode")) -> JSON.JSValue |]
  return $ (SigD fname sigt, FunD fname cclauses)

-- | Generates the \"load\" field for a single parameter.
--
-- There is custom handling, depending on how the parameter is
-- specified. For a 'Maybe' type parameter, we allow that it is not
-- present (via 'Utils.maybeFromObj'). Otherwise, if there is a
-- default value, we allow the parameter to be abset, and finally if
-- there is no default value, we require its presence.
loadField :: OpParam -> Q (Name, Stmt)
loadField (fname, qt, qdefa) = do
  let fvar = mkName fname
  t <- qt
  defa <- qdefa
  -- these are used in all patterns below
  let objvar = varNameE "o"
      objfield = stringE fname
  bexp <- if isOptional t
          then [| $((varNameE "maybeFromObj")) $objvar $objfield |]
          else case defa of
                 AppE (ConE dt) defval | dt == 'Just ->
                   -- but has a default value
                   [| $(varNameE "fromObjWithDefault")
                      $objvar $objfield $(return defval) |]
                 ConE dt | dt == 'Nothing ->
                     [| $(varNameE "fromObj") $objvar $objfield |]
                 s -> fail $ "Invalid default value " ++ show s ++
                      ", expecting either 'Nothing' or a 'Just defval'"
  return (fvar, BindS (VarP fvar) bexp)

loadConstructor :: String -> [OpParam] -> Q Exp
loadConstructor sname fields = do
  let name = mkName sname
  fbinds <- mapM loadField fields
  let (fnames, fstmts) = unzip fbinds
  let cval = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) fnames
      fstmts' = fstmts ++ [NoBindS (AppE (VarE 'return) cval)]
  return $ DoE fstmts'

genLoadOpCode :: [(String, [OpParam])] -> Q (Dec, Dec)
genLoadOpCode opdefs = do
  let fname = mkName "loadOpCode"
      arg1 = mkName "v"
      objname = mkName "o"
      opid = mkName "op_id"
  st1 <- bindS (varP objname) [| liftM JSON.fromJSObject
                                 (JSON.readJSON $(varE arg1)) |]
  st2 <- bindS (varP opid) [| $(varNameE "fromObj")
                              $(varE objname) $(stringE "OP_ID") |]
  -- the match results (per-constructor blocks)
  mexps <- mapM (uncurry loadConstructor) opdefs
  fails <- [| fail $ "Unknown opcode " ++ $(varE opid) |]
  let mpats = map (\(me, c) ->
                       let mp = LitP . StringL . deCamelCase . fst $ c
                       in Match mp (NormalB me) []
                  ) $ zip mexps opdefs
      defmatch = Match WildP (NormalB fails) []
      cst = NoBindS $ CaseE (VarE opid) $ mpats++[defmatch]
      body = DoE [st1, st2, cst]
  sigt <- [t| JSON.JSValue -> JSON.Result $(conT (mkName "OpCode")) |]
  return $ (SigD fname sigt, FunD fname [Clause [VarP arg1] (NormalB body) []])

-- | No default type.
noDefault :: Q Exp
noDefault = conE 'Nothing

-- * Template code for luxi

-- | Constructor-to-string for LuxiOp.
genStrOfOp :: Name -> String -> Q [Dec]
genStrOfOp = genConstrToStr id

-- | Constructor-to-string for MsgKeys.
genStrOfKey :: Name -> String -> Q [Dec]
genStrOfKey = genConstrToStr ensureLower

-- | LuxiOp parameter type.
type LuxiParam = (String, Q Type, Q Exp)

-- | Storage options for JSON.
data Store = SList | SDict

-- | Generates the LuxiOp data type.
--
-- This takes a Luxi operation definition and builds both the
-- datatype and the function trnasforming the arguments to JSON.
-- We can't use anything less generic, because the way different
-- operations are serialized differs on both parameter- and top-level.
--
-- There are three things to be defined for each parameter:
--
-- * name
--
-- * type
--
-- * operation; this is the operation performed on the parameter before
--   serialization
--
genLuxiOp :: String -> [(String, [LuxiParam], Store)] -> Q [Dec]
genLuxiOp name cons = do
  decl_d <- mapM (\(cname, fields, _) -> do
                    fields' <- mapM (\(_, qt, _) ->
                                         qt >>= \t -> return (NotStrict, t))
                               fields
                    return $ NormalC (mkName cname) fields')
            cons
  let declD = DataD [] (mkName name) [] decl_d [''Show, ''Read]
  (savesig, savefn) <- genSaveLuxiOp cons
  return [declD, savesig, savefn]

-- | Generates a Q Exp for an element, depending of the JSON return type.
helperLuxiField :: Store -> String -> Q Exp -> Q Exp
helperLuxiField SList name val = [| [ JSON.showJSON $val ] |]
helperLuxiField SDict name val = [| [(name, JSON.showJSON $val)] |]

-- | Generates the \"save\" expression for a single luxi parameter.
saveLuxiField :: Store -> Name -> LuxiParam -> Q Exp
saveLuxiField store fvar (fname, qt, fn) = do
  t <- qt
  let fvare = varE fvar
  (if isOptional t
   then [| case $fvare of
             Just v' ->
                 $(helperLuxiField store fname $ liftM2 appFn fn [| v' |])
             Nothing -> []
         |]
   else helperLuxiField store fname $ liftM2 appFn fn fvare)

-- | Generates final JSON Q Exp for constructor.
helperLuxiConstructor :: Store -> Q Exp -> Q Exp
helperLuxiConstructor SDict val = [| JSON.showJSON $ JSON.makeObj $val |]
helperLuxiConstructor SList val = [| JSON.JSArray $val |]

-- | Generates the \"save\" clause for entire LuxiOp constructor.
saveLuxiConstructor :: (String, [LuxiParam], Store) -> Q Clause
saveLuxiConstructor (sname, fields, store) = do
  let cname = mkName sname
      fnames = map (\(nm, _, _) -> mkName nm) fields
      pat = conP cname (map varP fnames)
      flist = map (uncurry $ saveLuxiField store) (zip fnames fields)
      flist' = appE [| concat |] (listE flist)
      finval = helperLuxiConstructor store flist'
  clause [pat] (normalB finval) []

-- | Generates the main save LuxiOp function.
genSaveLuxiOp :: [(String, [LuxiParam], Store)]-> Q (Dec, Dec)
genSaveLuxiOp opdefs = do
  sigt <- [t| $(conT (mkName "LuxiOp")) -> JSON.JSValue |]
  let fname = mkName "opToArgs"
  cclauses <- mapM saveLuxiConstructor opdefs
  return $ (SigD fname sigt, FunD fname cclauses)
