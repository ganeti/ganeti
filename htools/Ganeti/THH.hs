{-# LANGUAGE TemplateHaskell #-}

{-| TemplateHaskell helper for HTools.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

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

module Ganeti.THH ( declareSADT
                  , declareIADT
                  , makeJSONInstance
                  , genOpID
                  , genOpCode
                  , genStrOfOp
                  , genStrOfKey
                  , genLuxiOp
                  , Field
                  , simpleField
                  , defaultField
                  , optionalField
                  , renameField
                  , containerField
                  , customField
                  , timeStampFields
                  , uuidFields
                  , serialFields
                  , buildObject
                  , buildObjectSerialisation
                  , buildParam
                  , Container
                  ) where

import Control.Arrow
import Control.Monad (liftM, liftM2)
import Data.Char
import Data.List
import qualified Data.Map as M
import Language.Haskell.TH

import qualified Text.JSON as JSON

import Ganeti.HTools.JSON

-- * Exported types

type Container = M.Map String

-- | Serialised field data type.
data Field = Field { fieldName        :: String
                   , fieldType        :: Q Type
                   , fieldRead        :: Maybe (Q Exp)
                   , fieldShow        :: Maybe (Q Exp)
                   , fieldDefault     :: Maybe (Q Exp)
                   , fieldConstr      :: Maybe String
                   , fieldIsContainer :: Bool
                   , fieldIsOptional  :: Bool
                   }

-- | Generates a simple field.
simpleField :: String -> Q Type -> Field
simpleField fname ftype =
  Field { fieldName        = fname
        , fieldType        = ftype
        , fieldRead        = Nothing
        , fieldShow        = Nothing
        , fieldDefault     = Nothing
        , fieldConstr      = Nothing
        , fieldIsContainer = False
        , fieldIsOptional  = False
        }

-- | Sets the renamed constructor field.
renameField :: String -> Field -> Field
renameField constrName field = field { fieldConstr = Just constrName }

-- | Sets the default value on a field (makes it optional with a
-- default value).
defaultField :: Q Exp -> Field -> Field
defaultField defval field = field { fieldDefault = Just defval }

-- | Marks a field optional (turning its base type into a Maybe).
optionalField :: Field -> Field
optionalField field = field { fieldIsOptional = True }

-- | Marks a field as a container.
containerField :: Field -> Field
containerField field = field { fieldIsContainer = True }

-- | Sets custom functions on a field.
customField :: Q Exp -> Q Exp -> Field -> Field
customField readfn showfn field =
  field { fieldRead = Just readfn, fieldShow = Just showfn }

fieldRecordName :: Field -> String
fieldRecordName (Field { fieldName = name, fieldConstr = alias }) =
  maybe (camelCase name) id alias

-- | Computes the preferred variable name to use for the value of this
-- field. If the field has a specific constructor name, then we use a
-- first-letter-lowercased version of that; otherwise, we simply use
-- the field name. See also 'fieldRecordName'.
fieldVariable :: Field -> String
fieldVariable f =
  case (fieldConstr f) of
    Just name -> ensureLower name
    _ -> fieldName f

actualFieldType :: Field -> Q Type
actualFieldType f | fieldIsContainer f = [t| Container $t |]
                  | fieldIsOptional f  = [t| Maybe $t     |]
                  | otherwise = t
                  where t = fieldType f

checkNonOptDef :: (Monad m) => Field -> m ()
checkNonOptDef (Field { fieldIsOptional = True, fieldName = name }) =
  fail $ "Optional field " ++ name ++ " used in parameter declaration"
checkNonOptDef (Field { fieldDefault = (Just _), fieldName = name }) =
  fail $ "Default field " ++ name ++ " used in parameter declaration"
checkNonOptDef _ = return ()

loadFn :: Field -> Q Exp -> Q Exp
loadFn (Field { fieldIsContainer = True }) expr = [| $expr >>= readContainer |]
loadFn (Field { fieldRead = Just readfn }) expr = [| $expr >>= $readfn |]
loadFn _ expr = expr


-- * Common field declarations

timeStampFields :: [Field]
timeStampFields =
    [ defaultField [| 0::Double |] $ simpleField "ctime" [t| Double |]
    , defaultField [| 0::Double |] $ simpleField "mtime" [t| Double |]
    ]

serialFields :: [Field]
serialFields =
    [ renameField  "Serial" $ simpleField "serial_no" [t| Int |] ]

uuidFields :: [Field]
uuidFields = [ simpleField "uuid" [t| String |] ]

-- * Helper functions

-- | Ensure first letter is lowercase.
--
-- Used to convert type name to function prefix, e.g. in @data Aa ->
-- aaToRaw@.
ensureLower :: String -> String
ensureLower [] = []
ensureLower (x:xs) = toLower x:xs

-- | Ensure first letter is uppercase.
--
-- Used to convert constructor name to component
ensureUpper :: String -> String
ensureUpper [] = []
ensureUpper (x:xs) = toUpper x:xs

-- | Helper for quoted expressions.
varNameE :: String -> Q Exp
varNameE = varE . mkName

-- | showJSON as an expression, for reuse.
showJSONE :: Q Exp
showJSONE = varNameE "showJSON"

-- | ToRaw function name.
toRawName :: String -> Name
toRawName = mkName . (++ "ToRaw") . ensureLower

-- | FromRaw function name.
fromRawName :: String -> Name
fromRawName = mkName . (++ "FromRaw") . ensureLower

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

-- | Container loader
readContainer :: (Monad m, JSON.JSON a) =>
                 JSON.JSObject JSON.JSValue -> m (Container a)
readContainer obj = do
  let kjvlist = JSON.fromJSObject obj
  kalist <- mapM (\(k, v) -> fromKeyValue k v >>= \a -> return (k, a)) kjvlist
  return $ M.fromList kalist

-- | Container dumper
showContainer :: (JSON.JSON a) => Container a -> JSON.JSValue
showContainer = JSON.makeObj . map (second JSON.showJSON) . M.toList

-- * Template code for simple raw type-equivalent ADTs

-- | Generates a data type declaration.
--
-- The type will have a fixed list of instances.
strADTDecl :: Name -> [String] -> Dec
strADTDecl name constructors =
  DataD [] name []
          (map (flip NormalC [] . mkName) constructors)
          [''Show, ''Read, ''Eq, ''Enum, ''Bounded, ''Ord]

-- | Generates a toRaw function.
--
-- This generates a simple function of the form:
--
-- @
-- nameToRaw :: Name -> /traw/
-- nameToRaw Cons1 = var1
-- nameToRaw Cons2 = \"value2\"
-- @
genToRaw :: Name -> Name -> Name -> [(String, Either String Name)] -> Q [Dec]
genToRaw traw fname tname constructors = do
  let sigt = AppT (AppT ArrowT (ConT tname)) (ConT traw)
  -- the body clauses, matching on the constructor and returning the
  -- raw value
  clauses <- mapM  (\(c, v) -> clause [recP (mkName c) []]
                             (normalB (reprE v)) []) constructors
  return [SigD fname sigt, FunD fname clauses]

-- | Generates a fromRaw function.
--
-- The function generated is monadic and can fail parsing the
-- raw value. It is of the form:
--
-- @
-- nameFromRaw :: (Monad m) => /traw/ -> m Name
-- nameFromRaw s | s == var1       = Cons1
--               | s == \"value2\" = Cons2
--               | otherwise = fail /.../
-- @
genFromRaw :: Name -> Name -> Name -> [(String, Name)] -> Q [Dec]
genFromRaw traw fname tname constructors = do
  -- signature of form (Monad m) => String -> m $name
  sigt <- [t| (Monad m) => $(conT traw) -> m $(conT tname) |]
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
                 $(litE (stringL (nameBase tname))) ++ ": " ++ show $varpe) |]
    return (g, r)
  let fun = FunD fname [Clause [VarP varp]
                        (GuardedB (clauses++[oth_clause])) []]
  return [SigD fname sigt, fun]

-- | Generates a data type from a given raw format.
--
-- The format is expected to multiline. The first line contains the
-- type name, and the rest of the lines must contain two words: the
-- constructor name and then the string representation of the
-- respective constructor.
--
-- The function will generate the data type declaration, and then two
-- functions:
--
-- * /name/ToRaw, which converts the type to a raw type
--
-- * /name/FromRaw, which (monadically) converts from a raw type to the type
--
-- Note that this is basically just a custom show/read instance,
-- nothing else.
declareADT :: Name -> String -> [(String, Name)] -> Q [Dec]
declareADT traw sname cons = do
  let name = mkName sname
      ddecl = strADTDecl name (map fst cons)
      -- process cons in the format expected by genToRaw
      cons' = map (\(a, b) -> (a, Right b)) cons
  toraw <- genToRaw traw (toRawName sname) name cons'
  fromraw <- genFromRaw traw (fromRawName sname) name cons
  return $ ddecl:toraw ++ fromraw

declareIADT :: String -> [(String, Name)] -> Q [Dec]
declareIADT = declareADT ''Int

declareSADT :: String -> [(String, Name)] -> Q [Dec]
declareSADT = declareADT ''String

-- | Creates the showJSON member of a JSON instance declaration.
--
-- This will create what is the equivalent of:
--
-- @
-- showJSON = showJSON . /name/ToRaw
-- @
--
-- in an instance JSON /name/ declaration
genShowJSON :: String -> Q Dec
genShowJSON name = do
  body <- [| JSON.showJSON . $(varE (toRawName name)) |]
  return $ FunD (mkName "showJSON") [Clause [] (NormalB body) []]

-- | Creates the readJSON member of a JSON instance declaration.
--
-- This will create what is the equivalent of:
--
-- @
-- readJSON s = case readJSON s of
--                Ok s' -> /name/FromRaw s'
--                Error e -> Error /description/
-- @
--
-- in an instance JSON /name/ declaration
genReadJSON :: String -> Q Dec
genReadJSON name = do
  let s = mkName "s"
  body <- [| case JSON.readJSON $(varE s) of
               JSON.Ok s' -> $(varE (fromRawName name)) s'
               JSON.Error e ->
                   JSON.Error $ "Can't parse raw value for type " ++
                           $(stringE name) ++ ": " ++ e ++ " from " ++
                           show $(varE s)
           |]
  return $ FunD (mkName "readJSON") [Clause [VarP s] (NormalB body) []]

-- | Generates a JSON instance for a given type.
--
-- This assumes that the /name/ToRaw and /name/FromRaw functions
-- have been defined as by the 'declareSADT' function.
makeJSONInstance :: Name -> Q [Dec]
makeJSONInstance name = do
  let base = nameBase name
  showJ <- genShowJSON base
  readJ <- genReadJSON base
  return [InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name)) [readJ,showJ]]

-- * Template code for opcodes

-- | Transforms a CamelCase string into an_underscore_based_one.
deCamelCase :: String -> String
deCamelCase =
    intercalate "_" . map (map toUpper) . groupBy (\_ b -> not $ isUpper b)

-- | Transform an underscore_name into a CamelCase one.
camelCase :: String -> String
camelCase = concatMap (ensureUpper . drop 1) .
            groupBy (\_ b -> b /= '_') . ('_':)

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
-- 'genToRaw' to actually generate the function
genConstrToStr :: (String -> String) -> Name -> String -> Q [Dec]
genConstrToStr trans_fun name fname = do
  TyConI (DataD _ _ _ cons _) <- reify name
  cnames <- mapM (liftM nameBase . constructorName) cons
  let svalues = map (Left . trans_fun) cnames
  genToRaw ''String (mkName fname) name $ zip cnames svalues

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
genOpCode :: String                -- ^ Type name to use
          -> [(String, [Field])]   -- ^ Constructor name and parameters
          -> Q [Dec]
genOpCode name cons = do
  decl_d <- mapM (\(cname, fields) -> do
                    -- we only need the type of the field, without Q
                    fields' <- mapM actualFieldType fields
                    let fields'' = zip (repeat NotStrict) fields'
                    return $ NormalC (mkName cname) fields'')
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

-- | Generates the \"save\" clause for an entire opcode constructor.
--
-- This matches the opcode with variables named the same as the
-- constructor fields (just so that the spliced in code looks nicer),
-- and passes those name plus the parameter definition to 'saveObjectField'.
saveConstructor :: String    -- ^ The constructor name
                -> [Field]   -- ^ The parameter definitions for this
                             -- constructor
                -> Q Clause  -- ^ Resulting clause
saveConstructor sname fields = do
  let cname = mkName sname
  let fnames = map (mkName . fieldVariable) fields
  let pat = conP cname (map varP fnames)
  let felems = map (uncurry saveObjectField) (zip fnames fields)
      -- now build the OP_ID serialisation
      opid = [| [( $(stringE "OP_ID"),
                   JSON.showJSON $(stringE . deCamelCase $ sname) )] |]
      flist = listE (opid:felems)
      -- and finally convert all this to a json object
      flist' = [| $(varNameE "makeObj") (concat $flist) |]
  clause [pat] (normalB flist') []

-- | Generates the main save opcode function.
--
-- This builds a per-constructor match clause that contains the
-- respective constructor-serialisation code.
genSaveOpCode :: [(String, [Field])] -> Q (Dec, Dec)
genSaveOpCode opdefs = do
  cclauses <- mapM (uncurry saveConstructor) opdefs
  let fname = mkName "saveOpCode"
  sigt <- [t| $(conT (mkName "OpCode")) -> JSON.JSValue |]
  return $ (SigD fname sigt, FunD fname cclauses)

loadConstructor :: String -> [Field] -> Q Exp
loadConstructor sname fields = do
  let name = mkName sname
  fbinds <- mapM loadObjectField fields
  let (fnames, fstmts) = unzip fbinds
  let cval = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) fnames
      fstmts' = fstmts ++ [NoBindS (AppE (VarE 'return) cval)]
  return $ DoE fstmts'

genLoadOpCode :: [(String, [Field])] -> Q (Dec, Dec)
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

-- * Template code for luxi

-- | Constructor-to-string for LuxiOp.
genStrOfOp :: Name -> String -> Q [Dec]
genStrOfOp = genConstrToStr id

-- | Constructor-to-string for MsgKeys.
genStrOfKey :: Name -> String -> Q [Dec]
genStrOfKey = genConstrToStr ensureLower

-- | LuxiOp parameter type.
type LuxiParam = (String, Q Type, Q Exp)

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
genLuxiOp :: String -> [(String, [LuxiParam])] -> Q [Dec]
genLuxiOp name cons = do
  decl_d <- mapM (\(cname, fields) -> do
                    fields' <- mapM (\(_, qt, _) ->
                                         qt >>= \t -> return (NotStrict, t))
                               fields
                    return $ NormalC (mkName cname) fields')
            cons
  let declD = DataD [] (mkName name) [] decl_d [''Show, ''Read, ''Eq]
  (savesig, savefn) <- genSaveLuxiOp cons
  req_defs <- declareSADT "LuxiReq" .
              map (\(str, _) -> ("Req" ++ str, mkName ("luxiReq" ++ str))) $
                  cons
  return $ [declD, savesig, savefn] ++ req_defs

-- | Generates the \"save\" expression for a single luxi parameter.
saveLuxiField :: Name -> LuxiParam -> Q Exp
saveLuxiField fvar (_, qt, fn) =
    [| JSON.showJSON ( $(liftM2 appFn fn $ varE fvar) ) |]

-- | Generates the \"save\" clause for entire LuxiOp constructor.
saveLuxiConstructor :: (String, [LuxiParam]) -> Q Clause
saveLuxiConstructor (sname, fields) = do
  let cname = mkName sname
      fnames = map (\(nm, _, _) -> mkName nm) fields
      pat = conP cname (map varP fnames)
      flist = map (uncurry saveLuxiField) (zip fnames fields)
      finval = if null flist
               then [| JSON.showJSON ()    |]
               else [| JSON.showJSON $(listE flist) |]
  clause [pat] (normalB finval) []

-- | Generates the main save LuxiOp function.
genSaveLuxiOp :: [(String, [LuxiParam])]-> Q (Dec, Dec)
genSaveLuxiOp opdefs = do
  sigt <- [t| $(conT (mkName "LuxiOp")) -> JSON.JSValue |]
  let fname = mkName "opToArgs"
  cclauses <- mapM saveLuxiConstructor opdefs
  return $ (SigD fname sigt, FunD fname cclauses)

-- * "Objects" functionality

-- | Extract the field's declaration from a Field structure.
fieldTypeInfo :: String -> Field -> Q (Name, Strict, Type)
fieldTypeInfo field_pfx fd = do
  t <- actualFieldType fd
  let n = mkName . (field_pfx ++) . fieldRecordName $ fd
  return (n, NotStrict, t)

-- | Build an object declaration.
buildObject :: String -> String -> [Field] -> Q [Dec]
buildObject sname field_pfx fields = do
  let name = mkName sname
  fields_d <- mapM (fieldTypeInfo field_pfx) fields
  let decl_d = RecC name fields_d
  let declD = DataD [] name [] [decl_d] [''Show, ''Read, ''Eq]
  ser_decls <- buildObjectSerialisation sname fields
  return $ declD:ser_decls

buildObjectSerialisation :: String -> [Field] -> Q [Dec]
buildObjectSerialisation sname fields = do
  let name = mkName sname
  savedecls <- genSaveObject saveObjectField sname fields
  (loadsig, loadfn) <- genLoadObject loadObjectField sname fields
  shjson <- objectShowJSON sname
  rdjson <- objectReadJSON sname
  let instdecl = InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name))
                 [rdjson, shjson]
  return $ savedecls ++ [loadsig, loadfn, instdecl]

genSaveObject :: (Name -> Field -> Q Exp)
              -> String -> [Field] -> Q [Dec]
genSaveObject save_fn sname fields = do
  let name = mkName sname
  let fnames = map (mkName . fieldVariable) fields
  let pat = conP name (map varP fnames)
  let tdname = mkName ("toDict" ++ sname)
  tdsigt <- [t| $(conT name) -> [(String, JSON.JSValue)] |]

  let felems = map (uncurry save_fn) (zip fnames fields)
      flist = listE felems
      -- and finally convert all this to a json object
      tdlist = [| concat $flist |]
      iname = mkName "i"
  tclause <- clause [pat] (normalB tdlist) []
  cclause <- [| $(varNameE "makeObj") . $(varE tdname) |]
  let fname = mkName ("save" ++ sname)
  sigt <- [t| $(conT name) -> JSON.JSValue |]
  return [SigD tdname tdsigt, FunD tdname [tclause],
          SigD fname sigt, ValD (VarP fname) (NormalB cclause) []]

saveObjectField :: Name -> Field -> Q Exp
saveObjectField fvar field
  | isContainer = [| [( $nameE , JSON.showJSON . showContainer $ $fvarE)] |]
  | fisOptional = [| case $(varE fvar) of
                      Nothing -> []
                      Just v -> [( $nameE, JSON.showJSON v)]
                  |]
  | otherwise = case fieldShow field of
      Nothing -> [| [( $nameE, JSON.showJSON $fvarE)] |]
      Just fn -> [| [( $nameE, JSON.showJSON . $fn $ $fvarE)] |]
  where isContainer = fieldIsContainer field
        fisOptional  = fieldIsOptional field
        nameE = stringE (fieldName field)
        fvarE = varE fvar

objectShowJSON :: String -> Q Dec
objectShowJSON name = do
  body <- [| JSON.showJSON . $(varE . mkName $ "save" ++ name) |]
  return $ FunD (mkName "showJSON") [Clause [] (NormalB body) []]

genLoadObject :: (Field -> Q (Name, Stmt))
              -> String -> [Field] -> Q (Dec, Dec)
genLoadObject load_fn sname fields = do
  let name = mkName sname
      funname = mkName $ "load" ++ sname
      arg1 = mkName "v"
      objname = mkName "o"
      opid = mkName "op_id"
  st1 <- bindS (varP objname) [| liftM JSON.fromJSObject
                                 (JSON.readJSON $(varE arg1)) |]
  fbinds <- mapM load_fn fields
  let (fnames, fstmts) = unzip fbinds
  let cval = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) fnames
      fstmts' = st1:fstmts ++ [NoBindS (AppE (VarE 'return) cval)]
  sigt <- [t| JSON.JSValue -> JSON.Result $(conT name) |]
  return $ (SigD funname sigt,
            FunD funname [Clause [VarP arg1] (NormalB (DoE fstmts')) []])

loadObjectField :: Field -> Q (Name, Stmt)
loadObjectField field = do
  let name = fieldVariable field
      fvar = mkName name
  -- these are used in all patterns below
  let objvar = varNameE "o"
      objfield = stringE (fieldName field)
      loadexp =
        if fieldIsOptional field
          then [| $(varNameE "maybeFromObj") $objvar $objfield |]
          else case fieldDefault field of
                 Just defv ->
                   [| $(varNameE "fromObjWithDefault") $objvar
                      $objfield $defv |]
                 Nothing -> [| $(varNameE "fromObj") $objvar $objfield |]
  bexp <- loadFn field loadexp

  return (fvar, BindS (VarP fvar) bexp)

objectReadJSON :: String -> Q Dec
objectReadJSON name = do
  let s = mkName "s"
  body <- [| case JSON.readJSON $(varE s) of
               JSON.Ok s' -> $(varE .mkName $ "load" ++ name) s'
               JSON.Error e ->
                 JSON.Error $ "Can't parse value for type " ++
                       $(stringE name) ++ ": " ++ e
           |]
  return $ FunD (mkName "readJSON") [Clause [VarP s] (NormalB body) []]

-- * Inheritable parameter tables implementation

-- | Compute parameter type names.
paramTypeNames :: String -> (String, String)
paramTypeNames root = ("Filled"  ++ root ++ "Params",
                       "Partial" ++ root ++ "Params")

-- | Compute information about the type of a parameter field.
paramFieldTypeInfo :: String -> Field -> Q (Name, Strict, Type)
paramFieldTypeInfo field_pfx fd = do
  t <- actualFieldType fd
  let n = mkName . (++ "P") . (field_pfx ++) .
          fieldRecordName $ fd
  return (n, NotStrict, AppT (ConT ''Maybe) t)

-- | Build a parameter declaration.
--
-- This function builds two different data structures: a /filled/ one,
-- in which all fields are required, and a /partial/ one, in which all
-- fields are optional. Due to the current record syntax issues, the
-- fields need to be named differrently for the two structures, so the
-- partial ones get a /P/ suffix.
buildParam :: String -> String -> [Field] -> Q [Dec]
buildParam sname field_pfx fields = do
  let (sname_f, sname_p) = paramTypeNames sname
      name_f = mkName sname_f
      name_p = mkName sname_p
  fields_f <- mapM (fieldTypeInfo field_pfx) fields
  fields_p <- mapM (paramFieldTypeInfo field_pfx) fields
  let decl_f = RecC name_f fields_f
      decl_p = RecC name_p fields_p
  let declF = DataD [] name_f [] [decl_f] [''Show, ''Read, ''Eq]
      declP = DataD [] name_p [] [decl_p] [''Show, ''Read, ''Eq]
  ser_decls_f <- buildObjectSerialisation sname_f fields
  ser_decls_p <- buildPParamSerialisation sname_p fields
  fill_decls <- fillParam sname field_pfx fields
  return $ [declF, declP] ++ ser_decls_f ++ ser_decls_p ++ fill_decls

buildPParamSerialisation :: String -> [Field] -> Q [Dec]
buildPParamSerialisation sname fields = do
  let name = mkName sname
  savedecls <- genSaveObject savePParamField sname fields
  (loadsig, loadfn) <- genLoadObject loadPParamField sname fields
  shjson <- objectShowJSON sname
  rdjson <- objectReadJSON sname
  let instdecl = InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name))
                 [rdjson, shjson]
  return $ savedecls ++ [loadsig, loadfn, instdecl]

savePParamField :: Name -> Field -> Q Exp
savePParamField fvar field = do
  checkNonOptDef field
  let actualVal = mkName "v"
  normalexpr <- saveObjectField actualVal field
  -- we have to construct the block here manually, because we can't
  -- splice-in-splice
  return $ CaseE (VarE fvar) [ Match (ConP 'Nothing [])
                                       (NormalB (ConE '[])) []
                             , Match (ConP 'Just [VarP actualVal])
                                       (NormalB normalexpr) []
                             ]
loadPParamField :: Field -> Q (Name, Stmt)
loadPParamField field = do
  checkNonOptDef field
  let name = fieldName field
      fvar = mkName name
  -- these are used in all patterns below
  let objvar = varNameE "o"
      objfield = stringE name
      loadexp = [| $(varNameE "maybeFromObj") $objvar $objfield |]
  bexp <- loadFn field loadexp
  return (fvar, BindS (VarP fvar) bexp)

-- | Builds a simple declaration of type @n_x = fromMaybe f_x p_x@.
buildFromMaybe :: String -> Q Dec
buildFromMaybe fname =
  valD (varP (mkName $ "n_" ++ fname))
         (normalB [| $(varNameE "fromMaybe")
                        $(varNameE $ "f_" ++ fname)
                        $(varNameE $ "p_" ++ fname) |]) []

fillParam :: String -> String -> [Field] -> Q [Dec]
fillParam sname field_pfx fields = do
  let fnames = map (\fd -> field_pfx ++ fieldRecordName fd) fields
      (sname_f, sname_p) = paramTypeNames sname
      oname_f = "fobj"
      oname_p = "pobj"
      name_f = mkName sname_f
      name_p = mkName sname_p
      fun_name = mkName $ "fill" ++ sname ++ "Params"
      le_full = ValD (ConP name_f (map (VarP . mkName . ("f_" ++)) fnames))
                (NormalB . VarE . mkName $ oname_f) []
      le_part = ValD (ConP name_p (map (VarP . mkName . ("p_" ++)) fnames))
                (NormalB . VarE . mkName $ oname_p) []
      obj_new = foldl (\accu vname -> AppE accu (VarE vname)) (ConE name_f)
                $ map (mkName . ("n_" ++)) fnames
  le_new <- mapM buildFromMaybe fnames
  funt <- [t| $(conT name_f) -> $(conT name_p) -> $(conT name_f) |]
  let sig = SigD fun_name funt
      fclause = Clause [VarP (mkName oname_f), VarP (mkName oname_p)]
                (NormalB $ LetE (le_full:le_part:le_new) obj_new) []
      fun = FunD fun_name [fclause]
  return [sig, fun]
