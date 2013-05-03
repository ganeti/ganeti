{-# LANGUAGE TemplateHaskell #-}

{-| TemplateHaskell helper for Ganeti Haskell code.

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
                  , genAllConstr
                  , genAllOpIDs
                  , genOpCode
                  , genStrOfOp
                  , genStrOfKey
                  , genLuxiOp
                  , Field
                  , simpleField
                  , defaultField
                  , optionalField
                  , optionalNullSerField
                  , renameField
                  , customField
                  , timeStampFields
                  , uuidFields
                  , serialFields
                  , tagsFields
                  , TagSet
                  , buildObject
                  , buildObjectSerialisation
                  , buildParam
                  , DictObject(..)
                  , genException
                  , excErrMsg
                  ) where

import Control.Monad (liftM)
import Data.Char
import Data.List
import Data.Maybe (fromMaybe)
import qualified Data.Set as Set
import Language.Haskell.TH

import qualified Text.JSON as JSON
import Text.JSON.Pretty (pp_value)

import Ganeti.JSON

-- * Exported types

-- | Class of objects that can be converted to 'JSObject'
-- lists-format.
class DictObject a where
  toDict :: a -> [(String, JSON.JSValue)]

-- | Optional field information.
data OptionalType
  = NotOptional           -- ^ Field is not optional
  | OptionalOmitNull      -- ^ Field is optional, null is not serialised
  | OptionalSerializeNull -- ^ Field is optional, null is serialised
  deriving (Show, Eq)

-- | Serialised field data type.
data Field = Field { fieldName        :: String
                   , fieldType        :: Q Type
                   , fieldRead        :: Maybe (Q Exp)
                   , fieldShow        :: Maybe (Q Exp)
                   , fieldExtraKeys   :: [String]
                   , fieldDefault     :: Maybe (Q Exp)
                   , fieldConstr      :: Maybe String
                   , fieldIsOptional  :: OptionalType
                   }

-- | Generates a simple field.
simpleField :: String -> Q Type -> Field
simpleField fname ftype =
  Field { fieldName        = fname
        , fieldType        = ftype
        , fieldRead        = Nothing
        , fieldShow        = Nothing
        , fieldExtraKeys   = []
        , fieldDefault     = Nothing
        , fieldConstr      = Nothing
        , fieldIsOptional  = NotOptional
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
optionalField field = field { fieldIsOptional = OptionalOmitNull }

-- | Marks a field optional (turning its base type into a Maybe), but
-- with 'Nothing' serialised explicitly as /null/.
optionalNullSerField :: Field -> Field
optionalNullSerField field = field { fieldIsOptional = OptionalSerializeNull }

-- | Sets custom functions on a field.
customField :: Name      -- ^ The name of the read function
            -> Name      -- ^ The name of the show function
            -> [String]  -- ^ The name of extra field keys
            -> Field     -- ^ The original field
            -> Field     -- ^ Updated field
customField readfn showfn extra field =
  field { fieldRead = Just (varE readfn), fieldShow = Just (varE showfn)
        , fieldExtraKeys = extra }

-- | Computes the record name for a given field, based on either the
-- string value in the JSON serialisation or the custom named if any
-- exists.
fieldRecordName :: Field -> String
fieldRecordName (Field { fieldName = name, fieldConstr = alias }) =
  fromMaybe (camelCase name) alias

-- | Computes the preferred variable name to use for the value of this
-- field. If the field has a specific constructor name, then we use a
-- first-letter-lowercased version of that; otherwise, we simply use
-- the field name. See also 'fieldRecordName'.
fieldVariable :: Field -> String
fieldVariable f =
  case (fieldConstr f) of
    Just name -> ensureLower name
    _ -> map (\c -> if c == '-' then '_' else c) $ fieldName f

-- | Compute the actual field type (taking into account possible
-- optional status).
actualFieldType :: Field -> Q Type
actualFieldType f | fieldIsOptional f /= NotOptional = [t| Maybe $t |]
                  | otherwise = t
                  where t = fieldType f

-- | Checks that a given field is not optional (for object types or
-- fields which should not allow this case).
checkNonOptDef :: (Monad m) => Field -> m ()
checkNonOptDef (Field { fieldIsOptional = OptionalOmitNull
                      , fieldName = name }) =
  fail $ "Optional field " ++ name ++ " used in parameter declaration"
checkNonOptDef (Field { fieldIsOptional = OptionalSerializeNull
                      , fieldName = name }) =
  fail $ "Optional field " ++ name ++ " used in parameter declaration"
checkNonOptDef (Field { fieldDefault = (Just _), fieldName = name }) =
  fail $ "Default field " ++ name ++ " used in parameter declaration"
checkNonOptDef _ = return ()

-- | Produces the expression that will de-serialise a given
-- field. Since some custom parsing functions might need to use the
-- entire object, we do take and pass the object to any custom read
-- functions.
loadFn :: Field   -- ^ The field definition
       -> Q Exp   -- ^ The value of the field as existing in the JSON message
       -> Q Exp   -- ^ The entire object in JSON object format
       -> Q Exp   -- ^ Resulting expression
loadFn (Field { fieldRead = Just readfn }) expr o = [| $expr >>= $readfn $o |]
loadFn _ expr _ = expr

-- * Common field declarations

-- | Timestamp fields description.
timeStampFields :: [Field]
timeStampFields =
    [ defaultField [| 0::Double |] $ simpleField "ctime" [t| Double |]
    , defaultField [| 0::Double |] $ simpleField "mtime" [t| Double |]
    ]

-- | Serial number fields description.
serialFields :: [Field]
serialFields =
    [ renameField  "Serial" $ simpleField "serial_no" [t| Int |] ]

-- | UUID fields description.
uuidFields :: [Field]
uuidFields = [ simpleField "uuid" [t| String |] ]

-- | Tag set type alias.
type TagSet = Set.Set String

-- | Tag field description.
tagsFields :: [Field]
tagsFields = [ defaultField [| Set.empty |] $
               simpleField "tags" [t| TagSet |] ]

-- * Internal types

-- | A simple field, in constrast to the customisable 'Field' type.
type SimpleField = (String, Q Type)

-- | A definition for a single constructor for a simple object.
type SimpleConstructor = (String, [SimpleField])

-- | A definition for ADTs with simple fields.
type SimpleObject = [SimpleConstructor]

-- | A type alias for a constructor of a regular object.
type Constructor = (String, [Field])

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
showJSONE = varE 'JSON.showJSON

-- | makeObj as an expression, for reuse.
makeObjE :: Q Exp
makeObjE = varE 'JSON.makeObj

-- | fromObj (Ganeti specific) as an expression, for reuse.
fromObjE :: Q Exp
fromObjE = varE 'fromObj

-- | ToRaw function name.
toRawName :: String -> Name
toRawName = mkName . (++ "ToRaw") . ensureLower

-- | FromRaw function name.
fromRawName :: String -> Name
fromRawName = mkName . (++ "FromRaw") . ensureLower

-- | Converts a name to it's varE\/litE representations.
reprE :: Either String Name -> Q Exp
reprE = either stringE varE

-- | Smarter function application.
--
-- This does simply f x, except that if is 'id', it will skip it, in
-- order to generate more readable code when using -ddump-splices.
appFn :: Exp -> Exp -> Exp
appFn f x | f == VarE 'id = x
          | otherwise = AppE f x

-- | Builds a field for a normal constructor.
buildConsField :: Q Type -> StrictTypeQ
buildConsField ftype = do
  ftype' <- ftype
  return (NotStrict, ftype')

-- | Builds a constructor based on a simple definition (not field-based).
buildSimpleCons :: Name -> SimpleObject -> Q Dec
buildSimpleCons tname cons = do
  decl_d <- mapM (\(cname, fields) -> do
                    fields' <- mapM (buildConsField . snd) fields
                    return $ NormalC (mkName cname) fields') cons
  return $ DataD [] tname [] decl_d [''Show, ''Eq]

-- | Generate the save function for a given type.
genSaveSimpleObj :: Name                            -- ^ Object type
                 -> String                          -- ^ Function name
                 -> SimpleObject                    -- ^ Object definition
                 -> (SimpleConstructor -> Q Clause) -- ^ Constructor save fn
                 -> Q (Dec, Dec)
genSaveSimpleObj tname sname opdefs fn = do
  let sigt = AppT (AppT ArrowT (ConT tname)) (ConT ''JSON.JSValue)
      fname = mkName sname
  cclauses <- mapM fn opdefs
  return $ (SigD fname sigt, FunD fname cclauses)

-- * Template code for simple raw type-equivalent ADTs

-- | Generates a data type declaration.
--
-- The type will have a fixed list of instances.
strADTDecl :: Name -> [String] -> Dec
strADTDecl name constructors =
  DataD [] name []
          (map (flip NormalC [] . mkName) constructors)
          [''Show, ''Eq, ''Enum, ''Bounded, ''Ord]

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
-- Note that this is basically just a custom show\/read instance,
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
  return $ FunD 'JSON.showJSON [Clause [] (NormalB body) []]

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
  return $ FunD 'JSON.readJSON [Clause [VarP s] (NormalB body) []]

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
            groupBy (\_ b -> b /= '_' && b /= '-') . ('_':)

-- | Computes the name of a given constructor.
constructorName :: Con -> Q Name
constructorName (NormalC name _) = return name
constructorName (RecC name _)    = return name
constructorName x                = fail $ "Unhandled constructor " ++ show x

-- | Extract all constructor names from a given type.
reifyConsNames :: Name -> Q [String]
reifyConsNames name = do
  reify_result <- reify name
  case reify_result of
    TyConI (DataD _ _ _ cons _) -> mapM (liftM nameBase . constructorName) cons
    o -> fail $ "Unhandled name passed to reifyConsNames, expected\
                \ type constructor but got '" ++ show o ++ "'"

-- | Builds the generic constructor-to-string function.
--
-- This generates a simple function of the following form:
--
-- @
-- fname (ConStructorOne {}) = trans_fun("ConStructorOne")
-- fname (ConStructorTwo {}) = trans_fun("ConStructorTwo")
-- @
--
-- This builds a custom list of name\/string pairs and then uses
-- 'genToRaw' to actually generate the function.
genConstrToStr :: (String -> String) -> Name -> String -> Q [Dec]
genConstrToStr trans_fun name fname = do
  cnames <- reifyConsNames name
  let svalues = map (Left . trans_fun) cnames
  genToRaw ''String (mkName fname) name $ zip cnames svalues

-- | Constructor-to-string for OpCode.
genOpID :: Name -> String -> Q [Dec]
genOpID = genConstrToStr deCamelCase

-- | Builds a list with all defined constructor names for a type.
--
-- @
-- vstr :: String
-- vstr = [...]
-- @
--
-- Where the actual values of the string are the constructor names
-- mapped via @trans_fun@.
genAllConstr :: (String -> String) -> Name -> String -> Q [Dec]
genAllConstr trans_fun name vstr = do
  cnames <- reifyConsNames name
  let svalues = sort $ map trans_fun cnames
      vname = mkName vstr
      sig = SigD vname (AppT ListT (ConT ''String))
      body = NormalB (ListE (map (LitE . StringL) svalues))
  return $ [sig, ValD (VarP vname) body []]

-- | Generates a list of all defined opcode IDs.
genAllOpIDs :: Name -> String -> Q [Dec]
genAllOpIDs = genAllConstr deCamelCase

-- | OpCode parameter (field) type.
type OpParam = (String, Q Type, Q Exp)

-- | Generates the OpCode data type.
--
-- This takes an opcode logical definition, and builds both the
-- datatype and the JSON serialisation out of it. We can't use a
-- generic serialisation since we need to be compatible with Ganeti's
-- own, so we have a few quirks to work around.
genOpCode :: String        -- ^ Type name to use
          -> [Constructor] -- ^ Constructor name and parameters
          -> Q [Dec]
genOpCode name cons = do
  let tname = mkName name
  decl_d <- mapM (\(cname, fields) -> do
                    -- we only need the type of the field, without Q
                    fields' <- mapM (fieldTypeInfo "op") fields
                    return $ RecC (mkName cname) fields')
            cons
  let declD = DataD [] tname [] decl_d [''Show, ''Eq]

  let (allfsig, allffn) = genAllOpFields "allOpFields" cons
  save_decs <- genSaveOpCode tname "saveOpCode" "toDictOpCode"
               cons (uncurry saveConstructor) True
  (loadsig, loadfn) <- genLoadOpCode cons
  return $ [declD, allfsig, allffn, loadsig, loadfn] ++ save_decs

-- | Generates the function pattern returning the list of fields for a
-- given constructor.
genOpConsFields :: Constructor -> Clause
genOpConsFields (cname, fields) =
  let op_id = deCamelCase cname
      fvals = map (LitE . StringL) . sort . nub $
              concatMap (\f -> fieldName f:fieldExtraKeys f) fields
  in Clause [LitP (StringL op_id)] (NormalB $ ListE fvals) []

-- | Generates a list of all fields of an opcode constructor.
genAllOpFields  :: String        -- ^ Function name
                -> [Constructor] -- ^ Object definition
                -> (Dec, Dec)
genAllOpFields sname opdefs =
  let cclauses = map genOpConsFields opdefs
      other = Clause [WildP] (NormalB (ListE [])) []
      fname = mkName sname
      sigt = AppT  (AppT ArrowT (ConT ''String)) (AppT ListT (ConT ''String))
  in (SigD fname sigt, FunD fname (cclauses++[other]))

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
  fnames <- mapM (newName . fieldVariable) fields
  let pat = conP cname (map varP fnames)
  let felems = map (uncurry saveObjectField) (zip fnames fields)
      -- now build the OP_ID serialisation
      opid = [| [( $(stringE "OP_ID"),
                   JSON.showJSON $(stringE . deCamelCase $ sname) )] |]
      flist = listE (opid:felems)
      -- and finally convert all this to a json object
      flist' = [| concat $flist |]
  clause [pat] (normalB flist') []

-- | Generates the main save opcode function.
--
-- This builds a per-constructor match clause that contains the
-- respective constructor-serialisation code.
genSaveOpCode :: Name                      -- ^ Object ype
              -> String                    -- ^ To 'JSValue' function name
              -> String                    -- ^ To 'JSObject' function name
              -> [Constructor]             -- ^ Object definition
              -> (Constructor -> Q Clause) -- ^ Constructor save fn
              -> Bool                      -- ^ Whether to generate
                                           -- obj or just a
                                           -- list\/tuple of values
              -> Q [Dec]
genSaveOpCode tname jvalstr tdstr opdefs fn gen_object = do
  tdclauses <- mapM fn opdefs
  let typecon = ConT tname
      jvalname = mkName jvalstr
      jvalsig = AppT  (AppT ArrowT typecon) (ConT ''JSON.JSValue)
      tdname = mkName tdstr
  tdsig <- [t| $(return typecon) -> [(String, JSON.JSValue)] |]
  jvalclause <- if gen_object
                  then [| $makeObjE . $(varE tdname) |]
                  else [| JSON.showJSON . map snd . $(varE tdname) |]
  return [ SigD tdname tdsig
         , FunD tdname tdclauses
         , SigD jvalname jvalsig
         , ValD (VarP jvalname) (NormalB jvalclause) []]

-- | Generates load code for a single constructor of the opcode data type.
loadConstructor :: String -> [Field] -> Q Exp
loadConstructor sname fields = do
  let name = mkName sname
  fbinds <- mapM loadObjectField fields
  let (fnames, fstmts) = unzip fbinds
  let cval = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) fnames
      fstmts' = fstmts ++ [NoBindS (AppE (VarE 'return) cval)]
  return $ DoE fstmts'

-- | Generates the loadOpCode function.
genLoadOpCode :: [Constructor] -> Q (Dec, Dec)
genLoadOpCode opdefs = do
  let fname = mkName "loadOpCode"
      arg1 = mkName "v"
      objname = mkName "o"
      opid = mkName "op_id"
  st1 <- bindS (varP objname) [| liftM JSON.fromJSObject
                                 (JSON.readJSON $(varE arg1)) |]
  st2 <- bindS (varP opid) [| $fromObjE $(varE objname) $(stringE "OP_ID") |]
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

-- | Generates the LuxiOp data type.
--
-- This takes a Luxi operation definition and builds both the
-- datatype and the function transforming the arguments to JSON.
-- We can't use anything less generic, because the way different
-- operations are serialized differs on both parameter- and top-level.
--
-- There are two things to be defined for each parameter:
--
-- * name
--
-- * type
--
genLuxiOp :: String -> [Constructor] -> Q [Dec]
genLuxiOp name cons = do
  let tname = mkName name
  decl_d <- mapM (\(cname, fields) -> do
                    -- we only need the type of the field, without Q
                    fields' <- mapM actualFieldType fields
                    let fields'' = zip (repeat NotStrict) fields'
                    return $ NormalC (mkName cname) fields'')
            cons
  let declD = DataD [] (mkName name) [] decl_d [''Show, ''Eq]
  save_decs <- genSaveOpCode tname "opToArgs" "opToDict"
               cons saveLuxiConstructor False
  req_defs <- declareSADT "LuxiReq" .
              map (\(str, _) -> ("Req" ++ str, mkName ("luxiReq" ++ str))) $
                  cons
  return $ declD:save_decs ++ req_defs

-- | Generates the \"save\" clause for entire LuxiOp constructor.
saveLuxiConstructor :: Constructor -> Q Clause
saveLuxiConstructor (sname, fields) = do
  let cname = mkName sname
  fnames <- mapM (newName . fieldVariable) fields
  let pat = conP cname (map varP fnames)
  let felems = map (uncurry saveObjectField) (zip fnames fields)
      flist = [| concat $(listE felems) |]
  clause [pat] (normalB flist) []

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
  let declD = DataD [] name [] [decl_d] [''Show, ''Eq]
  ser_decls <- buildObjectSerialisation sname fields
  return $ declD:ser_decls

-- | Generates an object definition: data type and its JSON instance.
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

-- | The toDict function name for a given type.
toDictName :: String -> Name
toDictName sname = mkName ("toDict" ++ sname)

-- | Generates the save object functionality.
genSaveObject :: (Name -> Field -> Q Exp)
              -> String -> [Field] -> Q [Dec]
genSaveObject save_fn sname fields = do
  let name = mkName sname
  fnames <- mapM (newName . fieldVariable) fields
  let pat = conP name (map varP fnames)
  let tdname = toDictName sname
  tdsigt <- [t| $(conT name) -> [(String, JSON.JSValue)] |]

  let felems = map (uncurry save_fn) (zip fnames fields)
      flist = listE felems
      -- and finally convert all this to a json object
      tdlist = [| concat $flist |]
      iname = mkName "i"
  tclause <- clause [pat] (normalB tdlist) []
  cclause <- [| $makeObjE . $(varE tdname) |]
  let fname = mkName ("save" ++ sname)
  sigt <- [t| $(conT name) -> JSON.JSValue |]
  return [SigD tdname tdsigt, FunD tdname [tclause],
          SigD fname sigt, ValD (VarP fname) (NormalB cclause) []]

-- | Generates the code for saving an object's field, handling the
-- various types of fields that we have.
saveObjectField :: Name -> Field -> Q Exp
saveObjectField fvar field =
  case fieldIsOptional field of
    OptionalOmitNull -> [| case $(varE fvar) of
                             Nothing -> []
                             Just v  -> [( $nameE, JSON.showJSON v )]
                         |]
    OptionalSerializeNull -> [| case $(varE fvar) of
                                  Nothing -> [( $nameE, JSON.JSNull )]
                                  Just v  -> [( $nameE, JSON.showJSON v )]
                              |]
    NotOptional ->
      case fieldShow field of
        -- Note: the order of actual:extra is important, since for
        -- some serialisation types (e.g. Luxi), we use tuples
        -- (positional info) rather than object (name info)
        Nothing -> [| [( $nameE, JSON.showJSON $fvarE)] |]
        Just fn -> [| let (actual, extra) = $fn $fvarE
                      in ($nameE, JSON.showJSON actual):extra
                    |]
  where nameE = stringE (fieldName field)
        fvarE = varE fvar

-- | Generates the showJSON clause for a given object name.
objectShowJSON :: String -> Q Dec
objectShowJSON name = do
  body <- [| JSON.showJSON . $(varE . mkName $ "save" ++ name) |]
  return $ FunD 'JSON.showJSON [Clause [] (NormalB body) []]

-- | Generates the load object functionality.
genLoadObject :: (Field -> Q (Name, Stmt))
              -> String -> [Field] -> Q (Dec, Dec)
genLoadObject load_fn sname fields = do
  let name = mkName sname
      funname = mkName $ "load" ++ sname
      arg1 = mkName $ if null fields then "_" else "v"
      objname = mkName "o"
      opid = mkName "op_id"
  st1 <- bindS (varP objname) [| liftM JSON.fromJSObject
                                 (JSON.readJSON $(varE arg1)) |]
  fbinds <- mapM load_fn fields
  let (fnames, fstmts) = unzip fbinds
  let cval = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) fnames
      retstmt = [NoBindS (AppE (VarE 'return) cval)]
      -- FIXME: should we require an empty dict for an empty type?
      -- this allows any JSValue right now
      fstmts' = if null fields
                  then retstmt
                  else st1:fstmts ++ retstmt
  sigt <- [t| JSON.JSValue -> JSON.Result $(conT name) |]
  return $ (SigD funname sigt,
            FunD funname [Clause [VarP arg1] (NormalB (DoE fstmts')) []])

-- | Generates code for loading an object's field.
loadObjectField :: Field -> Q (Name, Stmt)
loadObjectField field = do
  let name = fieldVariable field
  fvar <- newName name
  -- these are used in all patterns below
  let objvar = varNameE "o"
      objfield = stringE (fieldName field)
      loadexp =
        if fieldIsOptional field /= NotOptional
          -- we treat both optional types the same, since
          -- 'maybeFromObj' can deal with both missing and null values
          -- appropriately (the same)
          then [| $(varE 'maybeFromObj) $objvar $objfield |]
          else case fieldDefault field of
                 Just defv ->
                   [| $(varE 'fromObjWithDefault) $objvar
                      $objfield $defv |]
                 Nothing -> [| $fromObjE $objvar $objfield |]
  bexp <- loadFn field loadexp objvar

  return (fvar, BindS (VarP fvar) bexp)

-- | Builds the readJSON instance for a given object name.
objectReadJSON :: String -> Q Dec
objectReadJSON name = do
  let s = mkName "s"
  body <- [| case JSON.readJSON $(varE s) of
               JSON.Ok s' -> $(varE .mkName $ "load" ++ name) s'
               JSON.Error e ->
                 JSON.Error $ "Can't parse value for type " ++
                       $(stringE name) ++ ": " ++ e
           |]
  return $ FunD 'JSON.readJSON [Clause [VarP s] (NormalB body) []]

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
  let declF = DataD [] name_f [] [decl_f] [''Show, ''Eq]
      declP = DataD [] name_p [] [decl_p] [''Show, ''Eq]
  ser_decls_f <- buildObjectSerialisation sname_f fields
  ser_decls_p <- buildPParamSerialisation sname_p fields
  fill_decls <- fillParam sname field_pfx fields
  return $ [declF, declP] ++ ser_decls_f ++ ser_decls_p ++ fill_decls ++
           buildParamAllFields sname fields ++
           buildDictObjectInst name_f sname_f

-- | Builds a list of all fields of a parameter.
buildParamAllFields :: String -> [Field] -> [Dec]
buildParamAllFields sname fields =
  let vname = mkName ("all" ++ sname ++ "ParamFields")
      sig = SigD vname (AppT ListT (ConT ''String))
      val = ListE $ map (LitE . StringL . fieldName) fields
  in [sig, ValD (VarP vname) (NormalB val) []]

-- | Builds the 'DictObject' instance for a filled parameter.
buildDictObjectInst :: Name -> String -> [Dec]
buildDictObjectInst name sname =
  [InstanceD [] (AppT (ConT ''DictObject) (ConT name))
   [ValD (VarP 'toDict) (NormalB (VarE (toDictName sname))) []]]

-- | Generates the serialisation for a partial parameter.
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

-- | Generates code to save an optional parameter field.
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

-- | Generates code to load an optional parameter field.
loadPParamField :: Field -> Q (Name, Stmt)
loadPParamField field = do
  checkNonOptDef field
  let name = fieldName field
  fvar <- newName name
  -- these are used in all patterns below
  let objvar = varNameE "o"
      objfield = stringE name
      loadexp = [| $(varE 'maybeFromObj) $objvar $objfield |]
  bexp <- loadFn field loadexp objvar
  return (fvar, BindS (VarP fvar) bexp)

-- | Builds a simple declaration of type @n_x = fromMaybe f_x p_x@.
buildFromMaybe :: String -> Q Dec
buildFromMaybe fname =
  valD (varP (mkName $ "n_" ++ fname))
         (normalB [| $(varE 'fromMaybe)
                        $(varNameE $ "f_" ++ fname)
                        $(varNameE $ "p_" ++ fname) |]) []

-- | Builds a function that executes the filling of partial parameter
-- from a full copy (similar to Python's fillDict).
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

-- * Template code for exceptions

-- | Exception simple error message field.
excErrMsg :: (String, Q Type)
excErrMsg = ("errMsg", [t| String |])

-- | Builds an exception type definition.
genException :: String                  -- ^ Name of new type
             -> SimpleObject -- ^ Constructor name and parameters
             -> Q [Dec]
genException name cons = do
  let tname = mkName name
  declD <- buildSimpleCons tname cons
  (savesig, savefn) <- genSaveSimpleObj tname ("save" ++ name) cons $
                         uncurry saveExcCons
  (loadsig, loadfn) <- genLoadExc tname ("load" ++ name) cons
  return [declD, loadsig, loadfn, savesig, savefn]

-- | Generates the \"save\" clause for an entire exception constructor.
--
-- This matches the exception with variables named the same as the
-- constructor fields (just so that the spliced in code looks nicer),
-- and calls showJSON on it.
saveExcCons :: String        -- ^ The constructor name
            -> [SimpleField] -- ^ The parameter definitions for this
                             -- constructor
            -> Q Clause      -- ^ Resulting clause
saveExcCons sname fields = do
  let cname = mkName sname
  fnames <- mapM (newName . fst) fields
  let pat = conP cname (map varP fnames)
      felems = if null fnames
                 then conE '() -- otherwise, empty list has no type
                 else listE $ map (\f -> [| JSON.showJSON $(varE f) |]) fnames
  let tup = tupE [ litE (stringL sname), felems ]
  clause [pat] (normalB [| JSON.showJSON $tup |]) []

-- | Generates load code for a single constructor of an exception.
--
-- Generates the code (if there's only one argument, we will use a
-- list, not a tuple:
--
-- @
-- do
--  (x1, x2, ...) <- readJSON args
--  return $ Cons x1 x2 ...
-- @
loadExcConstructor :: Name -> String -> [SimpleField] -> Q Exp
loadExcConstructor inname sname fields = do
  let name = mkName sname
  f_names <- mapM (newName . fst) fields
  let read_args = AppE (VarE 'JSON.readJSON) (VarE inname)
  let binds = case f_names of
                [x] -> BindS (ListP [VarP x])
                _   -> BindS (TupP (map VarP f_names))
      cval = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) f_names
  return $ DoE [binds read_args, NoBindS (AppE (VarE 'return) cval)]

{-| Generates the loadException function.

This generates a quite complicated function, along the lines of:

@
loadFn (JSArray [JSString name, args]) = case name of
   "A1" -> do
     (x1, x2, ...) <- readJSON args
     return $ A1 x1 x2 ...
   "a2" -> ...
   s -> fail $ "Unknown exception" ++ s
loadFn v = fail $ "Expected array but got " ++ show v
@
-}
genLoadExc :: Name -> String -> SimpleObject -> Q (Dec, Dec)
genLoadExc tname sname opdefs = do
  let fname = mkName sname
  exc_name <- newName "name"
  exc_args <- newName "args"
  exc_else <- newName "s"
  arg_else <- newName "v"
  fails <- [| fail $ "Unknown exception '" ++ $(varE exc_else) ++ "'" |]
  -- default match for unknown exception name
  let defmatch = Match (VarP exc_else) (NormalB fails) []
  -- the match results (per-constructor blocks)
  str_matches <-
    mapM (\(s, params) -> do
            body_exp <- loadExcConstructor exc_args s params
            return $ Match (LitP (StringL s)) (NormalB body_exp) [])
    opdefs
  -- the first function clause; we can't use [| |] due to TH
  -- limitations, so we have to build the AST by hand
  let clause1 = Clause [ConP 'JSON.JSArray
                               [ListP [ConP 'JSON.JSString [VarP exc_name],
                                            VarP exc_args]]]
                (NormalB (CaseE (AppE (VarE 'JSON.fromJSString)
                                        (VarE exc_name))
                          (str_matches ++ [defmatch]))) []
  -- the fail expression for the second function clause
  fail_type <- [| fail $ "Invalid exception: expected '(string, [args])' " ++
                  "      but got " ++ show (pp_value $(varE arg_else)) ++ "'"
                |]
  -- the second function clause
  let clause2 = Clause [VarP arg_else] (NormalB fail_type) []
  sigt <- [t| JSON.JSValue -> JSON.Result $(conT tname) |]
  return $ (SigD fname sigt, FunD fname [clause1, clause2])
