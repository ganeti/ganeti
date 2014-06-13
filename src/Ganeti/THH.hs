{-# LANGUAGE ParallelListComp, TemplateHaskell #-}

{-| TemplateHaskell helper for Ganeti Haskell code.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

-}

{-

Copyright (C) 2011, 2012, 2013, 2014 Google Inc.

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
                  , declareLADT
                  , declareILADT
                  , declareIADT
                  , makeJSONInstance
                  , deCamelCase
                  , genOpID
                  , genOpLowerStrip
                  , genAllConstr
                  , genAllOpIDs
                  , PyValue(..)
                  , PyValueEx(..)
                  , OpCodeField(..)
                  , OpCodeDescriptor(..)
                  , genOpCode
                  , genStrOfOp
                  , genStrOfKey
                  , genLuxiOp
                  , Field (..)
                  , simpleField
                  , andRestArguments
                  , withDoc
                  , defaultField
                  , optionalField
                  , optionalNullSerField
                  , renameField
                  , customField
                  , buildObject
                  , buildObjectSerialisation
                  , buildParam
                  , genException
                  , excErrMsg
                  ) where

import Control.Arrow ((&&&))
import Control.Applicative
import Control.Monad
import Control.Monad.Base () -- Needed to prevent spurious GHC linking errors.
import Control.Monad.Writer (tell)
import qualified Control.Monad.Trans as MT
import Data.Attoparsec () -- Needed to prevent spurious GHC 7.4 linking errors.
  -- See issue #683 and https://ghc.haskell.org/trac/ghc/ticket/4899
import Data.Char
import Data.Function (on)
import Data.List
import Data.Maybe
import qualified Data.Map as M
import qualified Data.Set as S
import Language.Haskell.TH
import Language.Haskell.TH.Syntax (lift)

import qualified Text.JSON as JSON
import Text.JSON.Pretty (pp_value)

import Ganeti.JSON
import Ganeti.PyValue
import Ganeti.THH.PyType


-- * Exported types

-- | Optional field information.
data OptionalType
  = NotOptional           -- ^ Field is not optional
  | OptionalOmitNull      -- ^ Field is optional, null is not serialised
  | OptionalSerializeNull -- ^ Field is optional, null is serialised
  | AndRestArguments      -- ^ Special field capturing all the remaining fields
                          -- as plain JSON values
  deriving (Show, Eq)

-- | Serialised field data type describing how to generate code for the field.
-- Each field has a type, which isn't captured in the type of the data type,
-- but is saved in the 'Q' monad in 'fieldType'.
--
-- Let @t@ be a type we want to parametrize the field with. There are the
-- following possible types of fields:
--
--   [Mandatory with no default.] Then @fieldType@ holds @t@,
--     @fieldDefault = Nothing@ and @fieldIsOptional = NotOptional@.
--
--   [Field with a default value.] Then @fieldType@ holds @t@ and
--     @fieldDefault = Just exp@ where @exp@ is an expression of type @t@ and
--    @fieldIsOptional = NotOptional@.
--
--   [Optional, no default value.] Then @fieldType@ holds @Maybe t@,
--     @fieldDefault = Nothing@ and @fieldIsOptional@ is either
--     'OptionalOmitNull' or 'OptionalSerializeNull'.
--
-- Optional fields with a default value are prohibited, as their main
-- intention is to represent the information that a request didn't contain
-- the field data.
--
-- /Custom (de)serialization:/
-- Field can have custom (de)serialization functions that are stored in
-- 'fieldRead' and 'fieldShow'. If they aren't provided, the default is to use
-- 'readJSON' and 'showJSON' for the field's type @t@. If they are provided,
-- the type of the contained deserializing expression must be
--
-- @
--   [(String, JSON.JSValue)] -> JSON.JSValue -> JSON.Result t
-- @
--
-- where the first argument carries the whole record in the case the
-- deserializing function needs to process additional information.
--
-- The type of the contained serializing experssion must be
--
-- @
--   t -> (JSON.JSValue, [(String, JSON.JSValue)])
-- @
--
-- where the result can provide extra JSON fields to include in the output
-- record (or just return @[]@ if they're not needed).
--
-- Note that for optional fields the type appearing in the custom functions
-- is still @t@. Therefore making a field optional doesn't change the
-- functions.
--
-- There is also a special type of optional field 'AndRestArguments' which
-- allows to parse any additional arguments not covered by other fields. There
-- can be at most one such special field and it's type must be
-- @Map String JSON.JSValue@. See also 'andRestArguments'.
data Field = Field { fieldName        :: String
                   , fieldType        :: Q Type
                     -- ^ the type of the field, @t@ for non-optional fields,
                     -- @Maybe t@ for optional ones.
                   , fieldRead        :: Maybe (Q Exp)
                     -- ^ an optional custom deserialization function of type
                     -- @[(String, JSON.JSValue)] -> JSON.JSValue ->
                     -- JSON.Result t@
                   , fieldShow        :: Maybe (Q Exp)
                     -- ^ an optional custom serialization function of type
                     -- @t -> (JSON.JSValue, [(String, JSON.JSValue)])@
                   , fieldExtraKeys   :: [String]
                     -- ^ a list of extra keys added by 'fieldShow'
                   , fieldDefault     :: Maybe (Q Exp)
                     -- ^ an optional default value of type @t@
                   , fieldConstr      :: Maybe String
                   , fieldIsOptional  :: OptionalType
                     -- ^ determines if a field is optional, and if yes,
                     -- how
                   , fieldDoc         :: String
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
        , fieldDoc         = ""
        }

-- | Generate an AndRestArguments catch-all field.
andRestArguments :: String -> Field
andRestArguments fname =
  Field { fieldName        = fname
        , fieldType        = [t| M.Map String JSON.JSValue |]
        , fieldRead        = Nothing
        , fieldShow        = Nothing
        , fieldExtraKeys   = []
        , fieldDefault     = Nothing
        , fieldConstr      = Nothing
        , fieldIsOptional  = AndRestArguments
        , fieldDoc         = ""
        }

withDoc :: String -> Field -> Field
withDoc doc field =
  field { fieldDoc = doc }

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
actualFieldType f | fieldIsOptional f `elem` [NotOptional, AndRestArguments] = t
                  | otherwise =  [t| Maybe $t |]
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

-- | Construct a function that parses a field value. If the field has
-- a custom 'fieldRead', it's applied to @o@ and used. Otherwise
-- @JSON.readJSON@ is used.
parseFn :: Field   -- ^ The field definition
        -> Q Exp   -- ^ The entire object in JSON object format
        -> Q Exp   -- ^ The resulting function that parses a JSON message
parseFn field o =
  let fnType = [t| JSON.JSValue -> JSON.Result $(fieldType field) |]
      expr = maybe [| readJSONWithDesc $(stringE $ fieldName field) False |]
                   (`appE` o) (fieldRead field)
  in sigE expr fnType

-- | Produces the expression that will de-serialise a given
-- field. Since some custom parsing functions might need to use the
-- entire object, we do take and pass the object to any custom read
-- functions.
loadFn :: Field   -- ^ The field definition
       -> Q Exp   -- ^ The value of the field as existing in the JSON message
       -> Q Exp   -- ^ The entire object in JSON object format
       -> Q Exp   -- ^ Resulting expression
loadFn field expr o = [| $expr >>= $(parseFn field o) |]

-- | Just as 'loadFn', but for optional fields.
loadFnOpt :: Field   -- ^ The field definition
          -> Q Exp   -- ^ The value of the field as existing in the JSON message
                     -- as Maybe
          -> Q Exp   -- ^ The entire object in JSON object format
          -> Q Exp   -- ^ Resulting expression
loadFnOpt field@(Field { fieldDefault = Just def }) expr o
  = case fieldIsOptional field of
      NotOptional -> [| $expr >>= maybe (return $def) $(parseFn field o) |]
      _           -> fail $ "Field " ++ fieldName field ++ ":\
                            \ A field can't be optional and\
                            \ have a default value at the same time."
loadFnOpt field expr o
  = [| $expr >>= maybe (return Nothing) (liftM Just . $(parseFn field o)) |]

-- * Internal types

-- | A simple field, in constrast to the customisable 'Field' type.
type SimpleField = (String, Q Type)

-- | A definition for a single constructor for a simple object.
type SimpleConstructor = (String, [SimpleField])

-- | A definition for ADTs with simple fields.
type SimpleObject = [SimpleConstructor]

-- | A type alias for an opcode constructor of a regular object.
type OpCodeConstructor = (String, Q Type, String, [Field], String)

-- | A type alias for a Luxi constructor of a regular object.
type LuxiConstructor = (String, [Field])

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
genFromRaw :: Name -> Name -> Name -> [(String, Either String Name)] -> Q [Dec]
genFromRaw traw fname tname constructors = do
  -- signature of form (Monad m) => String -> m $name
  sigt <- [t| (Monad m) => $(conT traw) -> m $(conT tname) |]
  -- clauses for a guarded pattern
  let varp = mkName "s"
      varpe = varE varp
  clauses <- mapM (\(c, v) -> do
                     -- the clause match condition
                     g <- normalG [| $varpe == $(reprE v) |]
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
declareADT
  :: (a -> Either String Name) -> Name -> String -> [(String, a)] -> Q [Dec]
declareADT fn traw sname cons = do
  let name = mkName sname
      ddecl = strADTDecl name (map fst cons)
      -- process cons in the format expected by genToRaw
      cons' = map (\(a, b) -> (a, fn b)) cons
  toraw <- genToRaw traw (toRawName sname) name cons'
  fromraw <- genFromRaw traw (fromRawName sname) name cons'
  return $ ddecl:toraw ++ fromraw

declareLADT :: Name -> String -> [(String, String)] -> Q [Dec]
declareLADT = declareADT Left

declareILADT :: String -> [(String, Int)] -> Q [Dec]
declareILADT sname cons = do
  consNames <- sequence [ newName ('_':n) | (n, _) <- cons ]
  consFns <- concat <$> sequence
             [ do sig <- sigD n [t| Int |]
                  let expr = litE (IntegerL (toInteger i))
                  fn <- funD n [clause [] (normalB expr) []]
                  return [sig, fn]
             | n <- consNames
             | (_, i) <- cons ]
  let cons' = [ (n, n') | (n, _) <- cons | n' <- consNames ]
  (consFns ++) <$> declareADT Right ''Int sname cons'

declareIADT :: String -> [(String, Name)] -> Q [Dec]
declareIADT = declareADT Right ''Int

declareSADT :: String -> [(String, Name)] -> Q [Dec]
declareSADT = declareADT Right ''String

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
  body <- [| $(varE (fromRawName name)) =<<
             readJSONWithDesc $(stringE name) True $(varE s) |]
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
genConstrToStr :: (String -> Q String) -> Name -> String -> Q [Dec]
genConstrToStr trans_fun name fname = do
  cnames <- reifyConsNames name
  svalues <- mapM (liftM Left . trans_fun) cnames
  genToRaw ''String (mkName fname) name $ zip cnames svalues

-- | Constructor-to-string for OpCode.
genOpID :: Name -> String -> Q [Dec]
genOpID = genConstrToStr (return . deCamelCase)

-- | Strips @Op@ from the constructor name, converts to lower-case
-- and adds a given prefix.
genOpLowerStrip :: String -> Name -> String -> Q [Dec]
genOpLowerStrip prefix =
    genConstrToStr (liftM ((prefix ++) . map toLower . deCamelCase)
                    . stripPrefixM "Op")
  where
    stripPrefixM :: String -> String -> Q String
    stripPrefixM pfx s = maybe (fail $ s ++ " doesn't start with " ++ pfx)
                               return
                         $ stripPrefix pfx s

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

-- * Python code generation

data OpCodeField = OpCodeField { ocfName :: String
                               , ocfType :: PyType
                               , ocfDefl :: Maybe PyValueEx
                               , ocfDoc  :: String
                               }

-- | Transfers opcode data between the opcode description (through
-- @genOpCode@) and the Python code generation functions.
data OpCodeDescriptor = OpCodeDescriptor { ocdName   :: String
                                         , ocdType   :: PyType
                                         , ocdDoc    :: String
                                         , ocdFields :: [OpCodeField]
                                         , ocdDescr  :: String
                                         }

-- | Optionally encapsulates default values in @PyValueEx@.
--
-- @maybeApp exp typ@ returns a quoted expression that encapsulates
-- the default value @exp@ of an opcode parameter cast to @typ@ in a
-- @PyValueEx@, if @exp@ is @Just@.  Otherwise, it returns a quoted
-- expression with @Nothing@.
maybeApp :: Maybe (Q Exp) -> Q Type -> Q Exp
maybeApp Nothing _ =
  [| Nothing |]

maybeApp (Just expr) typ =
  [| Just ($(conE (mkName "PyValueEx")) ($expr :: $typ)) |]

-- | Generates a Python type according to whether the field is
-- optional.
--
-- The type of created expression is PyType.
genPyType' :: OptionalType -> Q Type -> Q PyType
genPyType' opt typ = typ >>= pyOptionalType (opt /= NotOptional)

-- | Generates Python types from opcode parameters.
genPyType :: Field -> Q PyType
genPyType f = genPyType' (fieldIsOptional f) (fieldType f)

-- | Generates Python default values from opcode parameters.
genPyDefault :: Field -> Q Exp
genPyDefault f = maybeApp (fieldDefault f) (fieldType f)

pyField :: Field -> Q Exp
pyField f = genPyType f >>= \t ->
            [| OpCodeField $(stringE (fieldName f))
                           t
                           $(genPyDefault f)
                           $(stringE (fieldDoc f)) |]

-- | Generates a Haskell function call to "showPyClass" with the
-- necessary information on how to build the Python class string.
pyClass :: OpCodeConstructor -> Q Exp
pyClass (consName, consType, consDoc, consFields, consDscField) =
  do let pyClassVar = varNameE "showPyClass"
         consName' = stringE consName
     consType' <- genPyType' NotOptional consType
     let consDoc' = stringE consDoc
     [| OpCodeDescriptor $consName'
                         consType'
                         $consDoc'
                         $(listE $ map pyField consFields)
                         consDscField |]

-- | Generates a function called "pyClasses" that holds the list of
-- all the opcode descriptors necessary for generating the Python
-- opcodes.
pyClasses :: [OpCodeConstructor] -> Q [Dec]
pyClasses cons =
  do let name = mkName "pyClasses"
         sig = SigD name (AppT ListT (ConT ''OpCodeDescriptor))
     fn <- FunD name <$> (:[]) <$> declClause cons
     return [sig, fn]
  where declClause c =
          clause [] (normalB (ListE <$> mapM pyClass c)) []

-- | Converts from an opcode constructor to a Luxi constructor.
opcodeConsToLuxiCons :: OpCodeConstructor -> LuxiConstructor
opcodeConsToLuxiCons (x, _, _, y, _) = (x, y)

-- | Generates 'DictObject' instance for an op-code.
genOpCodeDictObject :: Name                -- ^ Type name to use
                    -> (LuxiConstructor -> Q Clause) -- ^ saving function
                    -> (LuxiConstructor -> Q Exp) -- ^ loading function
                    -> [LuxiConstructor] -- ^ Constructors
                    -> Q [Dec]
genOpCodeDictObject tname savefn loadfn cons = do
  tdclauses <- genSaveOpCode cons savefn
  fdclauses <- genLoadOpCode cons loadfn
  return [ InstanceD [] (AppT (ConT ''DictObject) (ConT tname))
           [ FunD 'toDict tdclauses
           , FunD 'fromDictWKeys fdclauses
           ]]

-- | Generates the OpCode data type.
--
-- This takes an opcode logical definition, and builds both the
-- datatype and the JSON serialisation out of it. We can't use a
-- generic serialisation since we need to be compatible with Ganeti's
-- own, so we have a few quirks to work around.
genOpCode :: String              -- ^ Type name to use
          -> [OpCodeConstructor] -- ^ Constructor name and parameters
          -> Q [Dec]
genOpCode name cons = do
  let tname = mkName name
  decl_d <- mapM (\(cname, _, _, fields, _) -> do
                    -- we only need the type of the field, without Q
                    fields' <- mapM (fieldTypeInfo "op") fields
                    return $ RecC (mkName cname) fields')
            cons
  let declD = DataD [] tname [] decl_d [''Show, ''Eq]
  let (allfsig, allffn) = genAllOpFields "allOpFields" cons
  -- DictObject
  let luxiCons = map opcodeConsToLuxiCons cons
  dictObjInst <- genOpCodeDictObject tname saveConstructor loadOpConstructor
                                     luxiCons
  -- rest
  pyDecls <- pyClasses cons
  return $ [declD, allfsig, allffn] ++ dictObjInst ++ pyDecls

-- | Generates the function pattern returning the list of fields for a
-- given constructor.
genOpConsFields :: OpCodeConstructor -> Clause
genOpConsFields (cname, _, _, fields, _) =
  let op_id = deCamelCase cname
      fvals = map (LitE . StringL) . sort . nub $
              concatMap (\f -> fieldName f:fieldExtraKeys f) fields
  in Clause [LitP (StringL op_id)] (NormalB $ ListE fvals) []

-- | Generates a list of all fields of an opcode constructor.
genAllOpFields  :: String              -- ^ Function name
                -> [OpCodeConstructor] -- ^ Object definition
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
saveConstructor :: LuxiConstructor -- ^ The constructor
                -> Q Clause        -- ^ Resulting clause
saveConstructor (sname, fields) = do
  let cname = mkName sname
  fnames <- mapM (newName . fieldVariable) fields
  let pat = conP cname (map varP fnames)
  let felems = zipWith saveObjectField fnames fields
      -- now build the OP_ID serialisation
      opid = [| [( $(stringE "OP_ID"),
                   JSON.showJSON $(stringE . deCamelCase $ sname) )] |]
      flist = listE (opid:felems)
      -- and finally convert all this to a json object
      flist' = [| concat $flist |]
  clause [pat] (normalB flist') []

-- | Generates the main save opcode function, serializing as a dictionary.
--
-- This builds a per-constructor match clause that contains the
-- respective constructor-serialisation code.
genSaveOpCode :: [LuxiConstructor]             -- ^ Object definition
              -> (LuxiConstructor -> Q Clause) -- ^ Constructor save fn
              -> Q [Clause]
genSaveOpCode opdefs fn = mapM fn opdefs

-- | Generates load code for a single constructor of the opcode data type.
-- The type of the resulting expression is @WriterT UsedKeys J.Result a@.
loadConstructor :: Name -> (Field -> Q Exp) -> [Field] -> Q Exp
loadConstructor name loadfn fields = do
  fnames <- mapM (newName . ("r_" ++) . fieldName) fields
  fexps <- mapM loadfn fields
  let fstmts = zipWith (BindS . VarP) fnames fexps
      cexp = foldl (\accu fn -> AppE accu (VarE fn)) (ConE name) fnames
      retstmt = [NoBindS (AppE (VarE 'return) cexp)]
      -- FIXME: should we require an empty dict for an empty type?
      -- this allows any JSValue right now
  [| MT.lift $(return $ DoE (fstmts ++ retstmt))
     <* tell $(fieldsUsedKeysQ fields) |]

-- | Generates load code for a single constructor of the opcode data type.
loadOpConstructor :: LuxiConstructor -> Q Exp
loadOpConstructor (sname, fields) =
  loadConstructor (mkName sname) (loadObjectField fields) fields

-- | Generates the loadOpCode function.
genLoadOpCode :: [LuxiConstructor]
              -> (LuxiConstructor -> Q Exp) -- ^ Constructor load fn
              -> Q [Clause]
genLoadOpCode opdefs fn = do
  let objname = objVarName
      opidKey = "OP_ID"
      opid = mkName $ map toLower opidKey
  st <- bindS (varP opid) [| $fromObjE $(varE objname) $(stringE opidKey) |]
  -- the match results (per-constructor blocks)
  mexps <- mapM fn opdefs
  fails <- [| fail $ "Unknown opcode " ++ $(varE opid) |]
  let mpats = map (\(me, op) ->
                       let mp = LitP . StringL . deCamelCase . fst $ op
                       in Match mp (NormalB me) []
                  ) $ zip mexps opdefs
      defmatch = Match WildP (NormalB fails) []
      cst = NoBindS $ CaseE (VarE opid) $ mpats++[defmatch]
      body = DoE [st, cst]
  -- include "OP_ID" to the list of used keys
  bodyAndOpId <- [| $(return body)
                    <* tell (mkUsedKeys $ S.singleton opidKey) |]
  return [Clause [VarP objname] (NormalB bodyAndOpId) []]

-- * Template code for luxi

-- | Constructor-to-string for LuxiOp.
genStrOfOp :: Name -> String -> Q [Dec]
genStrOfOp = genConstrToStr return

-- | Constructor-to-string for MsgKeys.
genStrOfKey :: Name -> String -> Q [Dec]
genStrOfKey = genConstrToStr (return . ensureLower)

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
genLuxiOp :: String -> [LuxiConstructor] -> Q [Dec]
genLuxiOp name cons = do
  let tname = mkName name
  decl_d <- mapM (\(cname, fields) -> do
                    -- we only need the type of the field, without Q
                    fields' <- mapM actualFieldType fields
                    let fields'' = zip (repeat NotStrict) fields'
                    return $ NormalC (mkName cname) fields'')
            cons
  let declD = DataD [] (mkName name) [] decl_d [''Show, ''Eq]
  -- generate DictObject instance
  dictObjInst <- genOpCodeDictObject tname saveLuxiConstructor
                                     loadOpConstructor cons
  -- .. and use it to construct 'opToArgs' of 'toDict'
  -- (as we know that the output of 'toDict' is always in the proper order)
  opToArgsType <- [t| $(conT tname) -> JSON.JSValue |]
  opToArgsExp <- [| JSON.showJSON . map snd . toDict |]
  let opToArgsName = mkName "opToArgs"
      opToArgsDecs = [ SigD opToArgsName opToArgsType
                     , ValD (VarP opToArgsName) (NormalB opToArgsExp) []
                     ]
  -- rest
  req_defs <- declareSADT "LuxiReq" .
              map (\(str, _) -> ("Req" ++ str, mkName ("luxiReq" ++ str))) $
                  cons
  return $ [declD] ++ dictObjInst ++ opToArgsDecs ++ req_defs

-- | Generates the \"save\" clause for entire LuxiOp constructor.
saveLuxiConstructor :: LuxiConstructor -> Q Clause
saveLuxiConstructor (sname, fields) = do
  let cname = mkName sname
  fnames <- mapM (newName . fieldVariable) fields
  let pat = conP cname (map varP fnames)
  let felems = zipWith saveObjectField fnames fields
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
  when (any ((==) AndRestArguments . fieldIsOptional)
         . drop 1 $ reverse fields)
    $ fail "Objects may have only one AndRestArguments field,\
           \ and it must be the last one."
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
  dictdecls <- genDictObject saveObjectField
                             (loadObjectField fields) sname fields
  savedecls <- genSaveObject sname
  (loadsig, loadfn) <- genLoadObject sname
  shjson <- objectShowJSON sname
  rdjson <- objectReadJSON sname
  let instdecl = InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name))
                 [rdjson, shjson]
  return $ dictdecls ++ savedecls ++ [loadsig, loadfn, instdecl]

-- | An internal name used for naming variables that hold the entire
-- object of type @[(String,JSValue)]@.
objVarName :: Name
objVarName = mkName "_o"

-- | Provides a default 'toJSArray' for 'ArrayObject' instance using its
-- existing 'DictObject' instance. The keys are serialized in the order
-- they're declared. The list must contain all keys possibly generated by
-- 'toDict'.
defaultToJSArray :: (DictObject a) => [String] -> a -> [JSON.JSValue]
defaultToJSArray keys o =
  let m = M.fromList $ toDict o
  in map (fromMaybe JSON.JSNull . flip M.lookup m) keys

-- | Provides a default 'fromJSArray' for 'ArrayObject' instance using its
-- existing 'DictObject' instance. The fields are deserialized in the order
-- they're declared.
defaultFromJSArray :: (DictObject a)
                   => [String] -> [JSON.JSValue] -> JSON.Result a
defaultFromJSArray keys xs = do
  let xslen = length xs
      explen = length keys
  unless (xslen == explen) (fail $ "Expected " ++ show explen
                                   ++ " arguments, got " ++ show xslen)
  fromDict $ zip keys xs

-- | Generates an additional 'ArrayObject' instance using its
-- existing 'DictObject' instance.
--
-- See 'defaultToJSArray' and 'defaultFromJSArray'.
genArrayObjectInstance :: Name -> [Field] -> Q Dec
genArrayObjectInstance name fields = do
  let fnames = concatMap (liftA2 (:) fieldName fieldExtraKeys) fields
  instanceD (return []) (appT (conT ''ArrayObject) (conT name))
    [ valD (varP 'toJSArray) (normalB [| defaultToJSArray $(lift fnames) |]) []
    , valD (varP 'fromJSArray) (normalB [| defaultFromJSArray fnames |]) []
    ]

-- | Generates 'DictObject' instance.
genDictObject :: (Name -> Field -> Q Exp)  -- ^ a saving function
              -> (Field -> Q Exp)          -- ^ a loading function
              -> String                    -- ^ an object name
              -> [Field]                   -- ^ a list of fields
              -> Q [Dec]
genDictObject save_fn load_fn sname fields = do
  let name = mkName sname
  -- toDict
  fnames <- mapM (newName . fieldVariable) fields
  let pat = conP name (map varP fnames)
      tdexp = [| concat $(listE $ zipWith save_fn fnames fields) |]
  tdclause <- clause [pat] (normalB tdexp) []
  -- fromDict
  fdexp <- loadConstructor name load_fn fields
  let fdclause = Clause [VarP objVarName] (NormalB fdexp) []
  -- the ArrayObject instance generated from DictObject
  arrdec <- genArrayObjectInstance name fields
  -- the final instance
  return $ [InstanceD [] (AppT (ConT ''DictObject) (ConT name))
             [ FunD 'toDict [tdclause]
             , FunD 'fromDictWKeys [fdclause]
             ]]
         ++ [arrdec]

-- | Generates the save object functionality.
genSaveObject :: String -> Q [Dec]
genSaveObject sname = do
  let fname = mkName ("save" ++ sname)
  sigt <- [t| $(conT $ mkName sname) -> JSON.JSValue |]
  cclause <- [| showJSONtoDict |]
  return [SigD fname sigt, ValD (VarP fname) (NormalB cclause) []]

-- | Generates the code for saving an object's field, handling the
-- various types of fields that we have.
saveObjectField :: Name -> Field -> Q Exp
saveObjectField fvar field = do
  let formatFn = fromMaybe [| JSON.showJSON &&& (const []) |] $
                           fieldShow field
      formatFnTyped = sigE formatFn
        [t| $(fieldType field) -> (JSON.JSValue, [(String, JSON.JSValue)]) |]
  let formatCode v = [| let (actual, extra) = $formatFnTyped $(v)
                         in ($nameE, actual) : extra |]
  case fieldIsOptional field of
    OptionalOmitNull ->       [| case $(fvarE) of
                                   Nothing -> []
                                   Just v  -> $(formatCode [| v |])
                              |]
    OptionalSerializeNull ->  [| case $(fvarE) of
                                   Nothing -> [( $nameE, JSON.JSNull )]
                                   Just v  -> $(formatCode [| v |])
                              |]
    NotOptional ->            formatCode fvarE
    AndRestArguments -> [| M.toList $(varE fvar) |]
  where nameE = stringE (fieldName field)
        fvarE = varE fvar

-- | Generates the showJSON clause for a given object name.
objectShowJSON :: String -> Q Dec
objectShowJSON name = do
  body <- [| JSON.showJSON . $(varE . mkName $ "save" ++ name) |]
  return $ FunD 'JSON.showJSON [Clause [] (NormalB body) []]

-- | Generates the load object functionality.
genLoadObject :: String -> Q (Dec, Dec)
genLoadObject sname = do
  let fname = mkName $ "load" ++ sname
  sigt <- [t| JSON.JSValue -> JSON.Result $(conT $ mkName sname) |]
  cclause <- [| readJSONfromDict |]
  return $ (SigD fname sigt,
            FunD fname [Clause [] (NormalB cclause) []])

-- | Generates code for loading an object's field.
loadObjectField :: [Field] -> Field -> Q Exp
loadObjectField allFields field = do
  let otherNames = fieldsDictKeysQ . filter (on (/=) fieldName field)
                                   $ allFields
  -- these are used in all patterns below
  let objvar = varE objVarName
      objfield = stringE (fieldName field)
  case (fieldDefault field, fieldIsOptional field) of
            -- Only non-optional fields without defaults must have a value;
            -- we treat both optional types the same, since
            -- 'maybeFromObj' can deal with both missing and null values
            -- appropriately (the same)
            (Nothing, NotOptional) ->
                  loadFn field [| fromObj $objvar $objfield |] objvar
            -- AndRestArguments need not to be parsed at all,
            -- they're just extracted from the list of other fields.
            (Nothing, AndRestArguments) ->
                  [| return . M.fromList
                     . filter (not . (`S.member` $(otherNames)) . fst)
                     $ $objvar |]
            _ ->  loadFnOpt field [| maybeFromObj $objvar $objfield |] objvar

-- | Generates the set of all used JSON dictionary keys for a field
fieldDictKeys :: Field -> Exp
fieldDictKeys field = AppE (VarE 'S.fromList)
  . ListE . map (LitE . StringL) $ liftA2 (:) fieldName fieldExtraKeys field

-- | Generates the list of all used JSON dictionary keys for a list of fields
fieldsDictKeys :: [Field] -> Exp
fieldsDictKeys fields =
  AppE (VarE 'S.unions) . ListE . map fieldDictKeys $ fields

-- | Generates the list of all used JSON dictionary keys for a list of fields
fieldsDictKeysQ :: [Field] -> Q Exp
fieldsDictKeysQ = return . fieldsDictKeys


-- | Generates the list of all used JSON dictionary keys for a list of fields,
-- depending on if any of them has 'AndRestArguments' flag.
fieldsUsedKeysQ :: [Field] -> Q Exp
fieldsUsedKeysQ fields
  | any ((==) AndRestArguments . fieldIsOptional) fields
              = [| allUsedKeys |]
  | otherwise = [| mkUsedKeys $(fieldsDictKeysQ fields) |]

-- | Builds the readJSON instance for a given object name.
objectReadJSON :: String -> Q Dec
objectReadJSON name = do
  let s = mkName "s"
  body <- [| $(varE . mkName $ "load" ++ name) =<<
             readJSONWithDesc $(stringE name) False $(varE s) |]
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
           buildParamAllFields sname fields

-- | Builds a list of all fields of a parameter.
buildParamAllFields :: String -> [Field] -> [Dec]
buildParamAllFields sname fields =
  let vname = mkName ("all" ++ sname ++ "ParamFields")
      sig = SigD vname (AppT ListT (ConT ''String))
      val = ListE $ map (LitE . StringL . fieldName) fields
  in [sig, ValD (VarP vname) (NormalB val) []]

-- | Generates the serialisation for a partial parameter.
buildPParamSerialisation :: String -> [Field] -> Q [Dec]
buildPParamSerialisation sname fields = do
  let name = mkName sname
  dictdecls <- genDictObject savePParamField loadPParamField sname fields
  savedecls <- genSaveObject sname
  (loadsig, loadfn) <- genLoadObject sname
  shjson <- objectShowJSON sname
  rdjson <- objectReadJSON sname
  let instdecl = InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name))
                 [rdjson, shjson]
  return $ dictdecls ++ savedecls ++ [loadsig, loadfn, instdecl]

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
loadPParamField :: Field -> Q Exp
loadPParamField field = do
  checkNonOptDef field
  let name = fieldName field
  -- these are used in all patterns below
  let objvar = varE objVarName
      objfield = stringE name
      loadexp = [| $(varE 'maybeFromObj) $objvar $objfield |]
  loadFnOpt field loadexp objvar

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
