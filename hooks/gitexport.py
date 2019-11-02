import yaml
import json
import datetime
from pprint import pprint
from pathlib import Path

import nbformat
import nbformat.sign
from nbformat.v4 import nbjson
import nbconvert
from nbconvert.preprocessors import Preprocessor, TagRemovePreprocessor
from nbconvert import HTMLExporter, NotebookExporter
from traitlets.config import Config
from traitlets import Unicode, Bool, Enum, default
from ipython_genutils import py3compat


# TODO: de-fancify
def get_cells_tagged(nb, tag='jekyll_front_matter',index=False):
    return [(x,i) if index else x for i,x in enumerate(nb.cells) if tag in x.get('metadata').get('tags',[])]


class MetadataPreprocessor(Preprocessor):
    """A preprocessor to populate meta data of raw cells"""
    
    update_front_matter = Bool(default_value=True,
        help=("Update metadata using front matter"
              "matches tags in `cell.metadata.tags`.")).tag(config=True)
        
    update_raw_cells = Bool(default_value=True,
        help=("Tag non-front matter raw cells for deletion"
              "matches tags in `cell.metadata.tags`.")).tag(config=True)
    
    def tag_raw_cells(self,nb):
        """Add metadata.tags to nbRaw cells
        
        This can fire every time.
        """
        raw_cells = [x for x in nb.cells if x['cell_type'] == 'raw']
        for cell in raw_cells: 
            cell.metadata['tags'] = cell.metadata.get('tags',[])
            # TODO: Restrictive/brittle, determine if flexibility is needed.
            tag_attr = 'jekyll_front_matter' if cell.source.startswith('---') else 'jekyll_raw_tag' 

            if tag_attr not in cell.metadata['tags']:
                cell.metadata['tags'].append(tag_attr)
        return raw_cells
    
    def fm_to_meta(self,nb):
        """Initially populates the metadata for conversion
        
        This cannot fire after GitHubPreprocessor converts to markdown header.
        It can fire again after GitHubPreprocessor reverts markdown cell to nbRaw cell (post-commit hook)
        """
    
        fm_cell = get_cells_tagged(nb, tag='jekyll_front_matter')[0]
        if fm_cell.cell_type != 'raw':
            print('WARN: Markdown header, no metadata updates occured.')
            return fm_cell
        
        # WARN: Depends on image credit html comment position, will likely change in future
        fm, img_credit = fm_cell.source.split('---')[1:] 
        fm_yaml = yaml.load(fm, Loader=yaml.FullLoader)
        
        # Format datetime as str for serialization 
        fm_yaml['date'] = str(fm_yaml['date'])#.strftime('%Y-%m-%d')
        fm_yaml['last_modified_at'] = str(fm_yaml['last_modified_at'])#.strftime('%Y-%m-%d')

        fm_cell.metadata['front_matter'] = fm_yaml #OrderedDict
        fm_cell.metadata['img_credit'] = img_credit
        return fm_cell

    def preprocess(self, nb, resources):
        # functions preform the opperations in place on notebook
        if self.update_raw_cells:
            self.log.info("Updating raw cell tags")
            _ = self.tag_raw_cells(nb)
        
        if self.update_front_matter: 
            self.log.info("Updating front matter")
            _ = self.fm_to_meta(nb)
        
        return nb, resources


class GitHubPreprocessor(Preprocessor):
    """A preprocessor to convert front matter to html"""
    
#     convert_tag = Unicode(default_value='jekyll_front_matter',
#         help=("Tag indicating which cell is to be converted to markdown from front matter,"
#               "matches tags in `cell.metadata.tags`.")).tag(config=True)
    
    header_type = Enum(['markdown','raw'], default_value='markdown',
                    help=("Format header cell for presentation (markdown) or front matter (raw),"
                         "valid options are {'markdown','raw'}")).tag(config=True)
    
    def meta_to_header(self, nb, cell_type='markdown', fm_tag='jekyll_front_matter'):
        """Run before pushing .ipynbs to github. Valid cell types: {'markdown','raw'}"""
    
        fm_cell = get_cells_tagged(nb, tag=fm_tag)[0]
        fm = fm_cell.metadata.front_matter

        if cell_type == 'markdown':
            template = ('<div style="color:#483D8B;text-align:center">\n'
                    '  <h1> {} </h1>\n''  <h3> {} </h3>\n''  <h4> Updated: {} </h4>\n''</div>')
            header = template.format(fm.title,fm.author,fm.last_modified_at)
        elif cell_type == 'raw': # cast as str to prevent pyyaml tags
            fm_yaml = yaml.dump(yaml.load(str(fm), Loader=yaml.FullLoader), sort_keys=False, explicit_start=True)+'---'
            header = fm_yaml+fm_cell.metadata.img_credit
        else:
            raise NotImplementedError("Valid `cell_type` options are {'markdown','raw'}")

        fm_cell.cell_type = cell_type
        fm_cell.source = header

        return fm_cell

    def preprocess(self, nb, resources):
        self.log.info("Converting cells marked", "to", self.header_type) #self.convert_tag
        _ = self.meta_to_header(nb,cell_type=self.header_type)  #fm_tag=self.convert_tag
        return nb, resources


class EmbeddingPreprocessor(Preprocessor):
    """A preprocessor to remove tagged raw cells and convert front matter to html"""
    
    header_type = Enum(['markdown','raw'], default_value='markdown',
                       help=("Format header cell for presentation (markdown) or front matter (raw),"
                             "valid options are {'markdown','raw'}")).tag(config=True)
    
    def _get_host_cells(self,nb):
        try:
            return [(nb.cells[i+1],i) for (x,i) in get_cells_tagged(nb,'jekyll_raw_tag',True)]
        except IndexError as ie:
            # Handle case when raw cell is last in notebook
            nb.cells.append(nbformat.v4.new_markdown_cell(source=' '))
            return self._get_host_cells(nb) # Wildly unnecessary recursion

    def inject_hosts(self,nb):
        # Populate host cells
        for cell,ridx in self._get_host_cells(nb):
            cell.metadata['nested'] = cell.metadata.get('nested',nb.cells[ridx])
        return nb

    def destroy_raw(self,nb,resources=None):
        # Destroy raw cells 
        trp = TagRemovePreprocessor(remove_cell_tags=['jekyll_raw_tag'])
        trp.preprocess(nb,resources)
    
    # @OPTIMIZE
    def restore_raw_cells(self,nb): 
        for x in nb.cells:
            if x.metadata.get('nested'):
                nb.cells.insert(nb.cells.index(x),x.metadata.pop('nested'))
        # recursively unnest raw cells. 
        if any(map(lambda x: x.metadata.hasattr('nested'), nb.cells)):
            return self.restore_raw_cells(nb)

        return nb
    
    def preprocess(self, nb, resources):
        self.log.info("Embedding and removing raw cells" if self.header_type == 'markdown' else "Unnesting and restoring raw cells")
        self.inject_hosts(nb)
        self.destroy_raw(nb,resources)
        if self.header_type == 'raw':
            self.restore_raw_cells(nb)
        return nb, resources


class JSONWriterUnsorted(nbjson.NotebookWriter):

    def writes(self, nb, **kwargs):
        """Serialize a NotebookNode object as a JSON string"""
        kwargs['cls'] = kwargs.get('cls',nbjson.BytesEncoder)
        kwargs['indent'] = kwargs.get('indent',1)
        kwargs['sort_keys'] = kwargs.get('sort_keys',False) # True
        kwargs['separators'] = kwargs.get('separators', (',',': '))
        kwargs.setdefault('ensure_ascii', False)
        # don't modify in-memory dict
        nb = nbjson.copy.deepcopy(nb)
        if kwargs.pop('split_lines', True):
            nb = nbjson.split_lines(nb)
        nb = nbjson.strip_transient(nb)
        # nbformat.validate(nb)
        return py3compat.cast_unicode_py2(json.dumps(nb, **kwargs), 'utf-8')
    
    def write(self, nb, fp, **kwargs):
        """Write a notebook to a file like object"""
        if isinstance(fp, (py3compat.unicode_type, bytes)):
            with open(fp, 'w', encoding='utf-8') as f:
                return self.write(nb, f, **kwargs)
            
        s = self.writes(nb, **kwargs)
        
        if isinstance(s, bytes): s = s.decode('utf8')
        fp.write(s)
        if not s.endswith(u'\n'): fp.write(u'\n')
        fp.close()
    
    def writex(self, nb, fp):
        s = self.writes(nb)
        with open(fp, 'w') as f:
            f.write(s)


class GitHubExporter(nbconvert.Exporter):
    
    nbformat_version = Enum(list(nbformat.versions), default_value=nbformat.current_nbformat,
        help="The nbformat version to write. Use this to downgrade notebooks.").tag(config=True)

    @default('file_extension')
    def _file_extension_default(self):
        return '.ipynb'

    output_mimetype = 'application/json'
    export_from_notebook = "Notebook"
    
    def from_notebook_node(self, nb, resources=None, **kw):
        nb_copy, resources = super(GitHubExporter, self).from_notebook_node(nb, resources, **kw)
        if self.nbformat_version != nb_copy.nbformat:
            resources['output_suffix'] = '.v%i' % self.nbformat_version
        else:
            resources['output_suffix'] = '.nbconvert'
        output = JSONWriterUnsorted().writes(nb_copy)
        output = output if output.endswith("\n") else output + "\n"
        return output, resources


def export_github(nb_file, outfile=None, header_type='markdown', rm_tag='jekyll_raw_tag', in_place=False):    
    c = Config() # convert_tag='jekyll_front_matter'
    c.MetadataPreprocessor.update_front_matter = True # TODO: make configurable
    c.MetadataPreprocessor.update_raw_cells = True # TODO: make configurable
    
    #c.GitHubPreprocessor.convert_tag = convert_tag
    c.GitHubPreprocessor.header_type = header_type
    c.EmbeddingPreprocessor.header_type = header_type

    #c.TagRemovePreprocessor.enabled=True # re-enable TagRemove https://github.com/jupyter/nbconvert/issues/764
    #c.TagRemovePreprocessor.remove_cell_tags = [rm_tag]
    
    c.GitHubExporter.preprocessors = [MetadataPreprocessor,GitHubPreprocessor,EmbeddingPreprocessor]#TagRemovePreprocessor]#'nbconvert.preprocessors.TagRemovePreprocessor']
    
    gh_notebook, res_ = GitHubExporter(config=c).from_filename(nb_file)
    nb = nbformat.reads(gh_notebook,nbformat.NO_CONVERT)
    
    if in_place:
        outfile = nb_file # ignores any value given to outfile
    else:
        if outfile is None:
            outfile = '_'.join(nb_file.split('_')[1:])
        else:
            opath=Path(outfile)
            opath.parent.mkdir(parents=True, exist_ok=True)
    
    nbformat.sign.TrustNotebookApp(config=c).sign_notebook(nb,outfile) # trust cells to correct visualizations
    JSONWriterUnsorted().write(nb,outfile) #nbformat.write(nb,outfile)
    print(f'Prepared file written to: {outfile}')


if __name__ == "__main__":
    import argparse
    # parse all with cmd: for /f %I in ('ls [0-9]*.ipynb -1') do python gitexport.py %I
    parser = argparse.ArgumentParser(prog='gitexport.py',description='Prepare notebook for github.')

    parser.add_argument('notebook', type=str,
                        help='.ipynb file to prepare')

    parser.add_argument('-o','--outfile', type=str, dest='outfile', metavar='OUT', 
                        help="destination output, defaults to overwritting file (default: notebook)")

    parser.add_argument('-t','--header-type', type=str, choices=['markdown','raw'], default='markdown', 
                        help="cell type of header cell (default: 'markdown')")

    parser.add_argument('-r','--rm-tag', type=str, default='jekyll_raw_tag',
                       help="metadata tag denoting cells to be removed (default: 'jekyll_raw_tag')")
    
    parser.add_argument('-i','--in-place',action='store_const', const=True, default=False,
                   help="flag indicates to overwrite file. If present, `outfile` is ignored")
    
    # parser.add_argument('-c','--convert-tag', type=str, default='jekyll_front_matter',
    #                    help="metadata tag denoting front matter cell to be converted (default: 'jekyll_front_matter')")

    args = parser.parse_args()
    export_github(nb_file=args.notebook, outfile=args.outfile, 
              header_type=args.header_type, rm_tag=args.rm_tag, in_place=args.in_place)
