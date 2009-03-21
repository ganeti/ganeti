{-| Scan clusters via RAPI and write instance/node data files.

-}

module Main (main) where

import Data.List
import Data.Function
import Data.Maybe(fromJust)
import Monad
import System
import System.IO
import System.FilePath
import System.Console.GetOpt
import qualified System

import Text.Printf (printf)

import qualified Ganeti.HTools.Container as Container
import qualified Ganeti.HTools.Cluster as Cluster
import qualified Ganeti.HTools.Version as Version
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import Ganeti.HTools.Rapi
import Ganeti.HTools.Utils

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool     -- ^ Whether to show node status
    , optOutPath   :: FilePath -- ^ Path to the output directory
    , optVerbose   :: Int      -- ^ Verbosity level
    , optShowVer   :: Bool     -- ^ Just show the program version
    , optNoHeader  :: Bool     -- ^ Do not show a header line
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optOutPath   = "."
 , optVerbose   = 0
 , optShowVer   = False
 , optNoHeader  = False
 }

-- | Options list and functions
options :: [OptDescr (Options -> Options)]
options =
    [ Option ['p']     ["print-nodes"]
      (NoArg (\ opts -> opts { optShowNodes = True }))
      "print the final node list"
    , Option ['d']     ["output-dir"]
      (ReqArg (\ d opts -> opts { optOutPath = d }) "PATH")
      "directory in which to write output files"
    , Option ['v']     ["verbose"]
      (NoArg (\ opts -> opts { optVerbose = (optVerbose opts) + 1 }))
      "increase the verbosity level"
    , Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option []        ["no-headers"]
      (NoArg (\ opts -> opts { optNoHeader = True }))
      "do not show a header line"
    ]

-- | Command line parser, using the 'options' structure.
parseOpts :: [String] -> IO (Options, [String])
parseOpts argv =
    case getOpt Permute options argv of
      (o, n, []) ->
          return (foldl (flip id) defaultOptions o, n)
      (_, _, errs) ->
          ioError (userError (concat errs ++ usageInfo header options))
      where header = printf "hscan %s\nUsage: hscan [OPTION...] cluster..."
                     Version.version

-- | Generate node file data from node objects
serializeNodes :: Cluster.NodeList -> String -> Cluster.NameList -> String
serializeNodes nl csf ktn =
    let etn = map (\(idx, name) -> (idx, name ++ csf)) ktn
        nodes = Container.elems nl
        nlines = map
                 (\node ->
                      let name = (fromJust $ lookup (Node.idx node) etn)
                          t_mem = (truncate $ Node.t_mem node)::Int
                          t_dsk = (truncate $ Node.t_dsk node)::Int
                      in
                        printf "%s|%d|%d|%d|%d" name
                                   t_mem (Node.f_mem node)
                                   t_dsk (Node.f_dsk node))
                 nodes
    in unlines nlines

-- | Generate instance file data from instance objects
serializeInstances :: Cluster.InstanceList -> String
                   -> Cluster.NameList -> Cluster.NameList -> String
serializeInstances il csf ktn kti =
    let etn = map (\(idx, name) -> (idx, name ++ csf)) ktn
        eti = map (\(idx, name) -> (idx, name ++ csf)) kti
        instances = Container.elems il
        nlines = map
                 (\inst ->
                      let
                          iname = fromJust $ lookup (Instance.idx inst) eti
                          pnode = fromJust $ lookup (Instance.pnode inst) etn
                          snode = fromJust $ lookup (Instance.snode inst) etn
                      in
                        printf "%s|%d|%d|%s|%s"
                               iname (Instance.mem inst) (Instance.dsk inst)
                               pnode snode
                 )
                 instances
    in unlines nlines

-- | Return a one-line summary of cluster state
printCluster :: Cluster.NodeList -> Cluster.InstanceList
             -> Cluster.NameList -> Cluster.NameList
             -> String
printCluster nl il ktn kti =
    let (bad_nodes, bad_instances) = Cluster.computeBadItems nl il
        ccv = Cluster.compCV nl
        nodes = Container.elems nl
        t_ram = truncate . sum . map Node.t_mem $ nodes
        t_dsk = truncate . sum . map Node.t_dsk $ nodes
        f_ram = sum . map Node.f_mem $ nodes
        f_dsk = sum . map Node.f_dsk $ nodes
    in
      printf "%5d %5d %5d %5d %6d %6d %6d %6d %.8f"
                 (length ktn) (length kti)
                 (length bad_nodes) (length bad_instances)
                 (t_ram::Integer) f_ram
                 ((t_dsk::Integer) `div` 1024) (f_dsk `div` 1024)
                 ccv


-- | Main function.
main :: IO ()
main = do
  cmd_args <- System.getArgs
  (opts, clusters) <- parseOpts cmd_args

  when (optShowVer opts) $ do
         putStr $ showVersion "hscan"
         exitWith ExitSuccess

  let odir = optOutPath opts
      nlen = maximum . map length $ clusters

  unless (optNoHeader opts) $
         printf "%-*s %5s %5s %5s %5s %6s %6s %6s %6s %10s\n" nlen
                "Name" "Nodes" "Inst" "BNode" "BInst" "t_mem" "f_mem"
                "t_disk" "f_disk" "Score"

  mapM (\ name ->
            do
              printf "%-*s " nlen name
              hFlush stdout
              node_data <- getNodes name
              inst_data <- getInstances name
              (if isLeft(node_data)
               then putStrLn $ fromLeft node_data
               else if isLeft(inst_data)
                    then putStrLn $ fromLeft inst_data
                    else do
                      let ndata = fromRight node_data
                          idata = fromRight inst_data
                          (nl, il, csf, ktn, kti) =
                              Cluster.loadData ndata idata
                      putStrLn $ printCluster nl il ktn kti
                      when (optShowNodes opts) $
                           putStr $ Cluster.printNodes ktn nl
                      let ndata = serializeNodes nl csf ktn
                          idata = serializeInstances il csf ktn kti
                          oname = odir </> name
                      writeFile (oname <.> "nodes") ndata
                      writeFile (oname <.> "instances") idata)
       ) clusters
  exitWith ExitSuccess
