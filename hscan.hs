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
import qualified Ganeti.HTools.Node as Node
import qualified Ganeti.HTools.Instance as Instance
import qualified Ganeti.HTools.CLI as CLI
import Ganeti.HTools.Rapi
import Ganeti.HTools.Utils

-- | Command line options structure.
data Options = Options
    { optShowNodes :: Bool     -- ^ Whether to show node status
    , optOutPath   :: FilePath -- ^ Path to the output directory
    , optVerbose   :: Int      -- ^ Verbosity level
    , optNoHeader  :: Bool     -- ^ Do not show a header line
    , optShowVer   :: Bool     -- ^ Just show the program version
    , optShowHelp  :: Bool     -- ^ Just show the help
    } deriving Show

-- | Default values for the command line options.
defaultOptions :: Options
defaultOptions  = Options
 { optShowNodes = False
 , optOutPath   = "."
 , optVerbose   = 0
 , optNoHeader  = False
 , optShowVer   = False
 , optShowHelp  = False
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
    , Option []        ["no-headers"]
      (NoArg (\ opts -> opts { optNoHeader = True }))
      "do not show a header line"
    , Option ['V']     ["version"]
      (NoArg (\ opts -> opts { optShowVer = True}))
      "show the version of the program"
    , Option ['h']     ["help"]
      (NoArg (\ opts -> opts { optShowHelp = True}))
      "show help"
    ]

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
                        printf "%s|%d|%d|%d|%d|%d|%c" name
                                   t_mem (Node.n_mem node) (Node.f_mem node)
                                   t_dsk (Node.f_dsk node)
                                   (if Node.offline node then 'Y' else 'N')
                 )
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
                        printf "%s|%d|%d|%s|%s|%s"
                               iname (Instance.mem inst) (Instance.dsk inst)
                               (Instance.run_st inst)
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
  (opts, clusters) <- CLI.parseOpts cmd_args "hscan" options
                      defaultOptions optShowHelp

  when (optShowVer opts) $ do
         putStr $ CLI.showVersion "hscan"
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
              (case node_data of
                 Bad err -> putStrLn err
                 Ok ndata ->
                     case inst_data of
                       Bad err -> putStrLn err
                       Ok idata ->
                           do
                             let  (nl, il, csf, ktn, kti) =
                                      Cluster.loadData ndata idata
                                  (_, fix_nl) = Cluster.checkData nl il ktn kti
                             putStrLn $ printCluster fix_nl il ktn kti
                             when (optShowNodes opts) $ do
                                      putStr $ Cluster.printNodes ktn fix_nl
                             let ndata = serializeNodes nl csf ktn
                                 idata = serializeInstances il csf ktn kti
                                 oname = odir </> name
                             writeFile (oname <.> "nodes") ndata
                             writeFile (oname <.> "instances") idata)
       ) clusters
  exitWith ExitSuccess
