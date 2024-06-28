#!/bin/bash
NB_DIR="../Pynbs"
for f in $NB_DIR/*.ipynb; do
    # ${${f##*/}%.ipynb};
    
    fname=${f##*/} # strip dir path
    fname=${fname%.ipynb} # strip ext
    
    # echo $fname
    # input/${fname}.ipynb
    jupyter nbconvert \
    --template numlesslab \
    --output-dir=out \
    --to html $f \
    --NbConvertApp.output_files_dir="assets/images/pyimgs/${fname}" \
    --ExtractOutputPreprocessor.enabled=True \
    --TemplateExporter.extra_template_basedirs=templates
    houtfile=out/${fname}.html
    # Prepend the frontmater yaml file to input, seperated by a single new line (\n)
    awk '{print $0}' $NB_DIR/frontmatter/${fname}.yaml $houtfile > ${houtfile}_tmp
    mv ${houtfile}_tmp $houtfile
    # replace local image asset path with rel html style
    # src="/assets/images
    # sed -i -e 's/src="assets/src="\/assets/g' $houtfile
    sed -i -e 's/src="assets\/images/src="\/assets\/images/g' $houtfile
    # surround any inline scripts with {% raw %} tags. Mostly for plot.ly, which uses {{}} and throws off liquid
    sed -i -e 's/<script/{% raw %}\n<script/g' $houtfile
    sed -i -e 's/<\/script>/<\/script>\n{% endraw %}/g' $houtfile
done