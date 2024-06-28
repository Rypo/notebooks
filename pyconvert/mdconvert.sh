#!/bin/bash
NB_DIR="../Pynbs"
for f in $NB_DIR/*.ipynb; do
    # ${${f##*/}%.ipynb};
    
    fname=${f##*/} # strip dir path
    fname=${fname%.ipynb} # strip ext
    
    # echo $fname
    # input/${fname}.ipynb \
    jupyter nbconvert \
    --template mdxhtml \
    --output-dir=mdout \
    --to markdown $f \
    --NbConvertApp.output_files_dir="assets/images/pyimgs/${fname}" \
    --ExtractOutputPreprocessor.enabled=True \
    --TemplateExporter.extra_template_basedirs=templates
    
    outfile=mdout/${fname}.md
    # Prepend the frontmater yaml file to input, seperated by a single new line (\n)
    awk '{print $0}' $NB_DIR/frontmatter/${fname}.yaml $outfile > ${outfile}_tmp
    mv ${outfile}_tmp $outfile
    # replace local image asset path with rel html style
    # src="/assets/images
    # sed -i -e 's/src="assets/src="\/assets/g' $outfile

    sed -i -e 's/assets\/images/\/assets\/images/g' $outfile
    # surround any inline scripts with {% raw %} tags. Mostly for plot.ly, which uses {{}} and throws off liquid
    sed -i -e 's/<script/{% raw %}\n<script/g' $outfile
    sed -i -e 's/<\/script>/<\/script>\n{% endraw %}/g' $outfile
done