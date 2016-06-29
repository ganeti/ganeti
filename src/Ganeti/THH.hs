{-# LANGUAGE ParallelListComp, TemplateHaskell #-}

{-| TemplateHaskell helper for Ganeti Haskell code.

As TemplateHaskell require that splices be defined in a separate
module, we combine all the TemplateHaskell functionality that HTools
needs in this module (except the one for unittests).

-}

{-

Copyright (C) 2011, 2012, 2013, 2014 Google Inc.
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
                  , notSerializeDefaultField
                  , presentInForthcoming
                  , optionalField
                  , optionalNullSerField
                  , makeOptional
                  , renameField
                  , customField
                  , buildObject
                  , buildObjectWithForthcoming
                  , buildObjectSerialisation
                  , buildParam
                  , genException
                  , excErrMsg
                  , ssconfConstructorName
                  ) where

import Control.Arrow ((&&&), second)
import Control.Applicative
import Control.Lens.Type (Lens, Lens')
import Control.Lens (lens, set, element)
import Control.Monad
import Control.Monad.Base () -- Needed to prevent spurious GHC linking errors.
import Control.Monad.Writer (tell)
import qualified Control.Monad.Trans as MT
import Data.Attoparsec.Text ()
  -- Needed to prevent spurious GHC 7.4 linking errors.
  -- See issue #683 and https://ghc.haskell.org/trac/ghc/ticket/4899
import Data.Char
import Data.Function (on)
import Data.List
import Data.Maybe
import qualified Data.Map as M
import Data.Monoid
import qualified Data.Set as S
import qualified Data.Text as T
import Language.Haskell.TH
import Language.Haskell.TH.Syntax (lift)

import qualified Text.JSON as JSON
import Text.JSON.Pretty (pp_value)

import Ganeti.JSON (readJSONWithDesc, fromObj, DictObject(..), ArrayObject(..), maybeFromObj, mkUsedKeys, showJSONtoDict, readJSONfromDict, branchOnField, addField, allUsedKeys)
import Ganeti.PartialParams
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
data Field = Field { fieldName        :: T.Text
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
                   , fieldExtraKeys   :: [T.Text]
                     -- ^ a list of extra keys added by 'fieldShow'
                   , fieldDefault     :: Maybe (Q Exp)
                     -- ^ an optional default value of type @t@
                   , fieldSerializeDefault :: Bool
                     -- ^ whether not presented default value will be
                     -- serialized
                   , fieldConstr      :: Maybe T.Text
                   , fieldIsOptional  :: OptionalType
                     -- ^ determines if a field is optional, and if yes,
                     -- how
                   , fieldDoc         :: T.Text
                   , fieldPresentInForthcoming :: Bool
                   }

-- | Generates a simple field.
simpleField :: String -> Q Type -> Field
simpleField fname ftype =
  Field { fieldName        = T.pack fname
        , fieldType        = ftype
        , fieldRead        = Nothing
        , fieldShow        = Nothing
        , fieldExtraKeys   = []
        , fieldDefault     = Nothing
        , fieldSerializeDefault = True
        , fieldConstr      = Nothing
        , fieldIsOptional  = NotOptional
        , fieldDoc         = T.pack ""
        , fieldPresentInForthcoming = False
        }

-- | Generate an AndRestArguments catch-all field.
andRestArguments :: String -> Field
andRestArguments fname =
  Field { fieldName        = T.pack fname
        , fieldType        = [t| M.Map String JSON.JSValue |]
        , fieldRead        = Nothing
        , fieldShow        = Nothing
        , fieldExtraKeys   = []
        , fieldDefault     = Nothing
        , fieldSerializeDefault = True
        , fieldConstr      = Nothing
        , fieldIsOptional  = AndRestArguments
        , fieldDoc         = T.pack ""
        , fieldPresentInForthcoming = True
        }

withDoc :: String -> Field -> Field
withDoc doc field =
  field { fieldDoc = T.pack doc }

-- | Sets the renamed constructor field.
renameField :: String -> Field -> Field
renameField constrName field = field { fieldConstr = Just $ T.pack constrName }

-- | Sets the default value on a field (makes it optional with a
-- default value).
defaultField :: Q Exp -> Field -> Field
defaultField defval field = field { fieldDefault = Just defval }

-- | A defaultField which will be serialized only if it's value differs from
-- a default value.
notSerializeDefaultField :: Q Exp -> Field -> Field
notSerializeDefaultField defval field =
  field { fieldDefault = Just defval
        , fieldSerializeDefault = False }

-- | Mark a field as present in the forthcoming variant.
presentInForthcoming :: Field -> Field
presentInForthcoming field = field { fieldPresentInForthcoming = True }

-- | Marks a field optional (turning its base type into a Maybe).
optionalField :: Field -> Field
optionalField field = field { fieldIsOptional = OptionalOmitNull }

-- | Marks a field optional (turning its base type into a Maybe), but
-- with 'Nothing' serialised explicitly as /null/.
optionalNullSerField :: Field -> Field
optionalNullSerField field = field { fieldIsOptional = OptionalSerializeNull }

-- | Make a field optional, if it isn't already.
makeOptional :: Field -> Field
makeOptional field = if  and [ fieldIsOptional field == NotOptional
                             , isNothing $ fieldDefault field
                             , not $ fieldPresentInForthcoming field
                             ]
                        then optionalField field
                        else field

-- | Sets custom functions on a field.
customField :: Name      -- ^ The name of the read function
            -> Name      -- ^ The name of the show function
            -> [String]  -- ^ The name of extra field keys
            -> Field     -- ^ The original field
            -> Field     -- ^ Updated field
customField readfn showfn extra field =
  field { fieldRead = Just (varE readfn), fieldShow = Just (varE showfn)
        , fieldExtraKeys = (map T.pack extra) }

-- | Computes the record name for a given field, based on either the
-- string value in the JSON serialisation or the custom named if any
-- exists.
fieldRecordName :: Field -> String
fieldRecordName (Field { fieldName = name, fieldConstr = alias }) =
  maybe (camelCase . T.unpack $ name) T.unpack alias

-- | Computes the preferred variable name to use for the value of this
-- field. If the field has a specific constructor name, then we use a
-- first-letter-lowercased version of that; otherwise, we simply use
-- the field name. See also 'fieldRecordName'.
fieldVariable :: Field -> String
fieldVariable f =
  case (fieldConstr f) of
    Just name -> ensureLower . T.unpack $ name
    _ -> map (\c -> if c == '-' then '_' else c) . T.unpack . fieldName $ f

-- | Compute the actual field type (taking into account possible
-- optional status).
actualFieldType :: Field -> Q Type
actualFieldType f | fieldIsOptional f `elem` [NotOptional, AndRestArguments] = t
                  | otherwise =  [t| Maybe $t |]
                  where t = fieldType f

-- | Checks that a given field is not optional (for object types or
-- fields which should not allow this case).
checkNonOptDef :: (Monad m) => Field -> m ()
checkNonOptDef field
  | fieldIsOptional field == OptionalOmitNull       = failWith kOpt
  | fieldIsOptional field == OptionalSerializeNull  = failWith kOpt
  | isJust (fieldDefault field)                     = failWith kDef
  | otherwise                                       = return ()
  where failWith kind = fail $ kind ++ " field " ++ name
                                    ++ " used in parameter declaration"
        name = T.unpack (fieldName field)
        kOpt = "Optional"
        kDef = "Default"

-- | Construct a function that parses a field value. If the field has
-- a custom 'fieldRead', it's applied to @o@ and used. Otherwise
-- @JSON.readJSON@ is used.
parseFn :: Field   -- ^ The field definition
        -> Q Exp   -- ^ The entire object in JSON object format
        -> Q Exp   -- ^ The resulting function that parses a JSON message
parseFn field o =
  let fnType = [t| JSON.JSValue -> JSON.Result $(fieldType field) |]
      expr = maybe
               [| readJSONWithDesc $(stringE . T.unpack $ fieldName field) |]
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
      _           -> fail $ "Field " ++ (T.unpack . fieldName $ field) ++ ":\
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

-- | Apply a constructor to a list of expressions
appCons :: Name -> [Exp] -> Exp
appCons cname = foldl AppE (ConE cname)

-- | Apply a constructor to a list of applicative expressions
appConsApp :: Name -> [Exp] -> Exp
appConsApp cname =
  foldl (\accu e -> InfixE (Just accu) (VarE '(<*>)) (Just e))
        (AppE (VarE 'pure) (ConE cname))

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
    let err = "Invalid string value for type " ++ (nameBase tname) ++ ": "
    g <- normalG [| otherwise |]
    r <- [|fail $ $(litE (stringL err)) ++ show $varpe |]
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
      cons' = map (second fn) cons
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
             readJSONWithDesc $(stringE name) $(varE s) |]
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
            [| OpCodeField $(stringE . T.unpack . fieldName $ f)
                           t
                           $(genPyDefault f)
                           $(stringE . T.unpack . fieldDoc $ f) |]

-- | Generates a Haskell function call to "showPyClass" with the
-- necessary information on how to build the Python class string.
pyClass :: OpCodeConstructor -> Q Exp
pyClass (consName, consType, consDoc, consFields, consDscField) =
  do let consName' = stringE consName
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
      fieldnames f = map T.unpack $ fieldName f:fieldExtraKeys f
      fvals = map (LitE . StringL) . sort . nub $ concatMap fieldnames fields
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
loadConstructor name loadfn fields =
  [| MT.lift $(appConsApp name <$> mapM loadfn fields)
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
                    <* tell (mkUsedKeys . S.singleton . T.pack $ opidKey) |]
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

-- | Build an accessor function for a field of an object
-- that can have a forthcoming variant.
buildAccessor :: Name -- ^ name of the forthcoming constructor
              -> String -- ^ prefix for the forthcoming field
              -> Name -- ^ name of the real constructor
              -> String -- ^ prefix for the real field
              -> Name -- ^ name of the generated accessor
              -> String -- ^ prefix of the generated accessor
              -> Field -- ^ field description
              -> Q [Dec]
buildAccessor fnm fpfx rnm rpfx nm pfx field = do
  let optField = makeOptional field
  x <- newName "x"
  (rpfx_name, _, _) <- fieldTypeInfo rpfx field
  (fpfx_name, _, ftype) <- fieldTypeInfo fpfx optField
  (pfx_name, _, _) <- fieldTypeInfo pfx field
  let r_body_core = AppE (VarE rpfx_name) $ VarE x
      r_body = if fieldIsOptional field == fieldIsOptional optField
                 then r_body_core
                 else AppE (VarE 'return) r_body_core
      f_body = AppE (VarE fpfx_name) $ VarE x
  return $ [ SigD pfx_name $ ArrowT `AppT` ConT nm `AppT` ftype
           , FunD pfx_name
             [ Clause [ConP rnm [VarP x]] (NormalB r_body) []
             , Clause [ConP fnm [VarP x]] (NormalB f_body) []
             ]]

-- | Build lense declartions for a field.
--
-- If the type of the field is the same in
-- the forthcoming and the real variant, the lens
-- will be a simple lens (Lens' s a).
--
-- Otherwise, the type will be (Lens s s (Maybe a) a).
-- This is because the field in forthcoming variant
-- has type (Maybe a), but the real variant has type a.
buildLens :: (Name, Name) -- ^ names of the forthcoming constructors
          -> (Name, Name) -- ^ names of the real constructors
          -> Name -- ^ name of the type
          -> String -- ^ the field prefix
          -> Int -- ^ arity
          -> (Field, Int) -- ^ the Field to generate the lens for, and its
                          -- position
          -> Q [Dec]
buildLens (fnm, fdnm) (rnm, rdnm) nm pfx ar (field, i) = do
  let optField = makeOptional field
      isSimple = fieldIsOptional field == fieldIsOptional optField
      lensnm = mkName $ pfx ++ fieldRecordName  field ++ "L"
  (accnm, _, ftype) <- fieldTypeInfo pfx field
  vars <- replicateM ar (newName "x")
  var <- newName "val"
  context <- newName "val"
  jE <- [| Just |]
  let body eJ cn cdn = NormalB
                      . (ConE cn `AppE`)
                      . foldl (\e (j, x) -> AppE e $
                                                if i == j
                                                  then if eJ
                                                    then AppE jE (VarE var)
                                                    else VarE var
                                                  else VarE x)
                        (ConE cdn)
                     $ zip [0..] vars
  let setterE = LamE [VarP context, VarP var] $ CaseE (VarE context)
                   [ Match (ConP fnm [ConP fdnm . set (element i) WildP
                                        $ map VarP vars])
                           (body (not isSimple) fnm fdnm) []
                   , Match (ConP rnm [ConP rdnm . set (element i) WildP
                                        $ map VarP vars])
                           (body False rnm rdnm) []
                   ]
  let lensD = ValD (VarP lensnm)
                     (NormalB  $ VarE 'lens `AppE` VarE accnm `AppE` setterE) []

  if isSimple
     then
       return $ (SigD lensnm $ ConT ''Lens' `AppT` ConT nm `AppT` ftype)
              : lensD : []
     else
       return $ (SigD lensnm $ ConT ''Lens `AppT`
                              ConT nm `AppT`
                              ConT nm `AppT`
                              (ConT ''Maybe `AppT` ftype) `AppT`
                              ftype)
              : lensD : []

-- | Build an object that can have a forthcoming variant.
-- This will create 3 data types: two objects, prefixed by
-- "Real" and "Forthcoming", respectively, and a sum type
-- of those. The JSON representation of the latter will
-- be a JSON object, dispatching on the "forthcoming" key.
buildObjectWithForthcoming ::
  String -- ^ Name of the newly defined type
  -> String -- ^ base prefix for field names; for the real and fortcoming
            -- variant, with base prefix will be prefixed with "real"
            -- and forthcoming, respectively.
  -> [Field] -- ^ List of fields in the real version
  -> Q [Dec]
buildObjectWithForthcoming sname field_pfx fields = do
  let capitalPrefix = ensureUpper field_pfx
      forth_nm = "Forthcoming" ++ sname
      forth_data_nm = forth_nm ++ "Data"
      forth_pfx = "forthcoming" ++ capitalPrefix
      real_nm =  "Real" ++ sname
      real_data_nm = real_nm ++ "Data"
      real_pfx = "real" ++ capitalPrefix
  concreteDecls <- buildObject real_data_nm real_pfx fields
  forthcomingDecls <- buildObject forth_data_nm forth_pfx
                      (map makeOptional fields)
  let name = mkName sname
      real_d = NormalC (mkName real_nm)
                 [(NotStrict, ConT (mkName real_data_nm))]
      forth_d = NormalC (mkName forth_nm)
                  [(NotStrict, ConT (mkName forth_data_nm))]
      declD = DataD [] name [] [real_d, forth_d] [''Show, ''Eq]

  read_body <- [| branchOnField "forthcoming"
                  (liftM $(conE $ mkName forth_nm) . JSON.readJSON)
                  (liftM $(conE $ mkName real_nm) . JSON.readJSON) |]
  x <- newName "x"
  show_real_body <- [| JSON.showJSON $(varE x) |]
  show_forth_body <- [| addField ("forthcoming", JSON.JSBool True)
                          $ JSON.showJSON $(varE x) |]
  let rdjson = FunD 'JSON.readJSON [Clause [] (NormalB read_body) []]
      shjson = FunD 'JSON.showJSON
                 [ Clause [ConP (mkName real_nm) [VarP x]]
                    (NormalB show_real_body) []
                 , Clause [ConP (mkName forth_nm) [VarP x]]
                    (NormalB show_forth_body) []
                 ]
      instJSONdecl = InstanceD [] (AppT (ConT ''JSON.JSON) (ConT name))
                     [rdjson, shjson]
  accessors <- liftM concat . flip mapM fields
                 $ buildAccessor (mkName forth_nm) forth_pfx
                                 (mkName real_nm) real_pfx
                                 name field_pfx
  lenses <- liftM concat . flip mapM (zip fields [0..])
              $ buildLens (mkName forth_nm, mkName forth_data_nm)
                          (mkName real_nm, mkName real_data_nm)
                          name field_pfx (length fields)
  xs <- newName "xs"
  fromDictWKeysbody <- [| if ("forthcoming", JSON.JSBool True) `elem` $(varE xs)
                            then liftM $(conE $ mkName forth_nm)
                                   (fromDictWKeys $(varE xs))
                            else liftM $(conE $ mkName real_nm)
                                   (fromDictWKeys $(varE xs)) |]
  todictx_r <- [| toDict $(varE x) |]
  todictx_f <- [| ("forthcoming", JSON.JSBool True) : toDict $(varE x) |]
  let todict = FunD 'toDict [ Clause [ConP (mkName real_nm) [VarP x]]
                               (NormalB todictx_r) []
                            , Clause [ConP (mkName forth_nm) [VarP x]]
                               (NormalB todictx_f) []
                            ]
      fromdict = FunD 'fromDictWKeys [ Clause [VarP xs]
                                       (NormalB fromDictWKeysbody) [] ]
      instDict = InstanceD [] (AppT (ConT ''DictObject) (ConT name))
                 [todict, fromdict]
  instArray <- genArrayObjectInstance name
                 (simpleField "forthcoming" [t| Bool |] : fields)
  let forthPredName = mkName $ field_pfx ++ "Forthcoming"
  let forthPredDecls = [ SigD forthPredName
                           $ ArrowT `AppT` ConT name `AppT` ConT ''Bool
                       , FunD forthPredName
                         [ Clause [ConP (mkName real_nm) [WildP]]
                                   (NormalB $ ConE 'False) []
                         , Clause [ConP (mkName forth_nm) [WildP]]
                                   (NormalB $ ConE 'True) []
                         ]
                       ]
  return $ concreteDecls ++ forthcomingDecls ++ [declD, instJSONdecl]
           ++ forthPredDecls ++ accessors ++ lenses ++ [instDict, instArray]

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
  let fnames = fieldsKeys fields
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
    NotOptional -> case (fieldDefault field, fieldSerializeDefault field) of
                     (Just v, False) -> [| if $v /= $fvarE
                                             then $(formatCode fvarE)
                                             else [] |]
                     -- If a default value exists and we shouldn't serialize
                     -- default fields - serialize only if the value differs
                     -- from the default one.
                     _ -> formatCode fvarE
    AndRestArguments -> [| M.toList $(varE fvar) |]
  where nameE = stringE (T.unpack . fieldName $ field)
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
      objfield = stringE (T.unpack . fieldName $ field)
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
               . filter (not . (`S.member` $(otherNames)) . T.pack . fst)
               $ $objvar |]
      _ ->  loadFnOpt field [| maybeFromObj $objvar $objfield |] objvar

fieldsKeys :: [Field] -> [String]
fieldsKeys fields =
  map T.unpack $ concatMap (liftA2 (:) fieldName fieldExtraKeys) fields

-- | Generates the set of all used JSON dictionary keys for a list of fields
-- The equivalent of S.fromList (map T.pack ["f1", "f2", "f3"] )
fieldsDictKeys :: [Field] -> Exp
fieldsDictKeys fields =
  AppE (VarE 'S.fromList)
  . AppE (AppE (VarE 'map) (VarE 'T.pack))
  . ListE . map (LitE . StringL)
  $ fieldsKeys fields

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
             readJSONWithDesc $(stringE name) $(varE s) |]
  return $ FunD 'JSON.readJSON [Clause [VarP s] (NormalB body) []]

-- * Inheritable parameter tables implementation

-- | Compute parameter type names.
paramTypeNames :: String -> (String, String)
paramTypeNames root = ("Filled"  ++ root ++ "Params",
                       "Partial" ++ root ++ "Params")

-- | Compute the name of a full and a partial parameter field.
paramFieldNames :: String -> Field -> (Name, Name)
paramFieldNames field_pfx fd =
  let base = field_pfx ++ fieldRecordName fd
   in (mkName base, mkName (base ++ "P"))

-- | Compute information about the type of a parameter field.
paramFieldTypeInfo :: String -> Field -> VarStrictTypeQ
paramFieldTypeInfo field_pfx fd = do
  t <- actualFieldType fd
  return (snd $ paramFieldNames field_pfx fd, NotStrict, AppT (ConT ''Maybe) t)

-- | Build a parameter declaration.
--
-- This function builds two different data structures: a /filled/ one,
-- in which all fields are required, and a /partial/ one, in which all
-- fields are optional. Due to the current record syntax issues, the
-- fields need to be named differrently for the two structures, so the
-- partial ones get a /P/ suffix.
-- Also generate a default value for the partial parameters.
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
      val = ListE $ map (LitE . StringL . T.unpack . fieldName) fields
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
      objfield = stringE . T.unpack $ name
      loadexp = [| $(varE 'maybeFromObj) $objvar $objfield |]
  loadFnOpt field loadexp objvar

-- | Builds a function that executes the filling of partial parameter
-- from a full copy (similar to Python's fillDict).
fillParam :: String -> String -> [Field] -> Q [Dec]
fillParam sname field_pfx fields = do
  let (sname_f, sname_p) = paramTypeNames sname
      name_f = mkName sname_f
      name_p = mkName sname_p
  let (fnames, pnames) = unzip $ map (paramFieldNames field_pfx) fields
  -- due to apparent bugs in some older GHC versions, we need to add these
  -- prefixes to avoid "binding shadows ..." errors
  fbinds <- mapM (newName . ("f_" ++) . nameBase) fnames
  let fConP = ConP name_f (map VarP fbinds)
  pbinds <- mapM (newName . ("p_" ++) . nameBase) pnames
  let pConP = ConP name_p (map VarP pbinds)
  -- PartialParams instance --------
  -- fillParams
  let fromMaybeExp fn pn = AppE (AppE (VarE 'fromMaybe) (VarE fn)) (VarE pn)
      fupdates = appCons name_f $ zipWith fromMaybeExp fbinds pbinds
      fclause = Clause [fConP, pConP] (NormalB fupdates) []
  -- toPartial
  let tpupdates = appCons name_p $ map (AppE (ConE 'Just) . VarE) fbinds
      tpclause = Clause [fConP] (NormalB tpupdates) []
  -- toFilled
  let tfupdates = appConsApp name_f $ map VarE pbinds
      tfclause = Clause [pConP] (NormalB tfupdates) []
  -- the instance
  let instType = AppT (AppT (ConT ''PartialParams) (ConT name_f)) (ConT name_p)
  -- Monoid instance for the partial part ----
  -- mempty
  let memptyExp = appCons name_p $ map (const $ VarE 'empty) fields
      memptyClause = Clause [] (NormalB memptyExp) []
  -- mappend
  pbinds2 <- mapM (newName . ("p2_" ++) . nameBase) pnames
  let pConP2 = ConP name_p (map VarP pbinds2)
  -- note the reversal of 'l' and 'r' in the call to <|>
  -- as we want the result to be the rightmost value
  let altExp = zipWith (\l r -> AppE (AppE (VarE '(<|>)) (VarE r)) (VarE l))
      mappendExp = appCons name_p $ altExp pbinds pbinds2
      mappendClause = Clause [pConP, pConP2] (NormalB mappendExp) []
  let monoidType = AppT (ConT ''Monoid) (ConT name_p)
  -- the instances combined
  return [ InstanceD [] instType
                     [ FunD 'fillParams [fclause]
                     , FunD 'toPartial [tpclause]
                     , FunD 'toFilled [tfclause]
                     ]
         , InstanceD [] monoidType
                     [ FunD 'mempty [memptyClause]
                     , FunD 'mappend [mappendClause]
                     ]]

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
      cval = appCons name $ map VarE f_names
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
  let err = "Invalid exception: expected '(string, [args])' " ++
            "      but got "
  fail_type <- [| fail $ err ++ show (pp_value $(varE arg_else)) ++ "'" |]
  -- the second function clause
  let clause2 = Clause [VarP arg_else] (NormalB fail_type) []
  sigt <- [t| JSON.JSValue -> JSON.Result $(conT tname) |]
  return $ (SigD fname sigt, FunD fname [clause1, clause2])

-- | Compute the ssconf constructor name from its file name.
ssconfConstructorName :: String -> String
ssconfConstructorName = camelCase . ("s_s_" ++)
