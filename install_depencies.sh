while read -r url; do
    wget -P static/local_libs "$url"
done < dependencies.txt