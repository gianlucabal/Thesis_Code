import json
import tifffile
import numpy as np
from datetime import datetime
from lxml import etree 
import h5py
import numpy as np
import os
import time

DATI_PATH =r"webapi-LAME-main\file_manager\plugin\dati.txt"

def print_dictionary(dizionario):
    """
    Prints a dictionary in a formatted, readable way (recursively handles nested dictionaries).
    """
    for chiave, valore in dizionario.items():
        if isinstance(valore, dict):
            print(f"{chiave}:")
            print_dictionary(valore)  # Chiamata ricorsiva per i dizionari annidati
        else:
            print(f"{chiave}: {valore}")

def metadata_extractor_tiff(tiff_path):
    """Extracts metadata from a TIFF file and returns it as a dictionary."""
    metadata = {}

    with tifffile.TiffFile(tiff_path) as tif:
        page = tif.pages[0]  # Consider only the first page for simplicity
        for tag in page.tags.values():
            tag_name = tag.name
            tag_value = tag.value

            # Handle type conversions
            if isinstance(tag_value, datetime):
                tag_value = tag_value.isoformat()
            elif isinstance(tag_value, np.ndarray):
                tag_value = tag_value.tolist()
            elif isinstance(tag_value, bytes):
                try:
                    tag_value = tag_value.decode(errors='replace')  # tenta di decodificare
                except Exception:
                    tag_value = tag_value.hex()
            elif isinstance(tag_value, dict):
                # Flatten inner dictionary into flat metadata structure
                for key, value in tag_value.items():
                    metadata[f"{value[0]}"] = value[1:]
                continue  # salta inserimento diretto

            metadata[tag_name] = tag_value

    return metadata


def extract_fields(element, path=""):
    fields = []

    # Add the root <definition> node as a special field
    if element.tag.endswith("definition"):
        definition_str = etree.tostring(element, encoding="unicode", pretty_print=False)
        fields.append({
            "path": f"{path}/field:definition",
            "name": "definition",
            "type": "NX_XML",
            "value": "NXem"
        })

    for child in element:
        if not isinstance(child.tag, str):
            continue  # Ignore comments or processing instructions

        tag = etree.QName(child).localname
        name = child.get("name") or child.get("type") or "unnamed"
        current_path = f"{path}/{tag}:{name}"

        if tag == "field":
            # Look for enumeration value if present
            enumeration_item = child.find(".//{http://definition.nexusformat.org/nxdl/3.1}enumeration/{http://definition.nexusformat.org/nxdl/3.1}item")
            enum_value = enumeration_item.get("value") if enumeration_item is not None else None

            field_entry = {
                "path": current_path,
                "name": child.get("name"),
                "type": child.get("type"),
                "value": enum_value  # Usa il valore se c'è, altrimenti None
            }
            fields.append(field_entry)

            # Add any attributes defined inside the field
            for attr in child.findall(".//{http://definition.nexusformat.org/nxdl/3.1}attribute"):
                attr_name = attr.get("name")
                attr_type = attr.get("type")
                attr_path = f"{current_path}/attribute:{attr_name}"
                fields.append({
                    "path": attr_path,
                    "name": attr_name,
                    "type": attr_type,
                    "value": None
                })

        elif tag == "group":
            fields.extend(extract_fields(child, current_path))

    return fields



def create_schema_from_xml(xml_path):
    # Parse XML schema
    tree = etree.parse(xml_path)
    root = tree.getroot()
    # Extract schema info
    fields_info = extract_fields(root)
    # JSON output will have the same base name as the XML input
    base_name = os.path.splitext(xml_path)[0]
    output_json = base_name + ".json"
    # Write JSON to disk
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(fields_info, f, indent=4, ensure_ascii=False)
    print(f"File JSON salvato come {output_json}")
    return fields_info



def load_json(json_path):
    print(f"Loading JSON schema from {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_or_create_group(root, path_parts):
    grp = root
    for part in path_parts:
        if part not in grp:
            grp = grp.create_group(part)
        else:
            grp = grp[part]
    return grp

def insert_metadati(metadata_path, metadati):# returns the value to insert into NeXus based on metadata mapping
    if metadata_path is not None:
        #print(f"Path metadati: {metadata_path}")
        if metadata_path.startswith("§s"):  # stringa definita nello schema
            #print(f"s metadata_path: {metadata_path}")    
            value = metadata_path.removeprefix("§s")
        elif metadata_path.startswith("§l"):  # link simbolico
            #print(f"l metadata_path: {metadata_path}") 
            value = metadata_path.removeprefix("§l")
        elif metadata_path.startswith("§e"):  # embedded stringa (es. XML)
            #print(f"e metadata_path: {metadata_path}") 
            value = metadata_path
        else:  # è un campo da cercare nei metadati TIFF
            value = metadati.get(metadata_path)
    else:
        value = None
    #print(f"Valore estratto: {value}")
    return value

# build_nexus_from_tiff_TEM_ED  nel mio file è rimasto il nome dello script precedente  
def build_nexus_from_tiff_TEM_ED(tiff_path=None, mapping_json_path=None,  out_nxs=None, extra_fields=None):

    instrument_data = load_json(DATI_PATH)   # external data not found in TIFF or the GUI form, may be needed now or in future
    metadati = metadata_extractor_tiff(tiff_path[0])  # only extract once from the first TIFF
    metadati.update(instrument_data)  # Merge extracted metadata with manually provided data    
    metadati.update(extra_fields)  # Merge extracted metadata with manually provided data
    unique_name=metadati.get("unique_name") # unique name is defined in the config file (e.g., 'Nanotech_labE_Merlin_')
    unique_filename = f"{unique_name.replace(' ', '_')}_{int(time.time())}.nxs"
    nexus_file_path = os.path.join(out_nxs,unique_filename)

    with h5py.File(nexus_file_path, "w") as f:
        # Root-level attributes
        f.attrs["NX_class"] = "NXroot"
        f.attrs["file_name"] = os.path.abspath(nexus_file_path)
        f.attrs["file_time"] = datetime.now().isoformat()
        f.attrs["h5py_version"] = h5py.version.version
        f.attrs["HDF5_Version"] = h5py.version.hdf5_version

        # Iterate over schema items
        schema_json = load_json(mapping_json_path)
        for item in schema_json:
            path = item["path"]
            metadata_path = item["value"]
            nx_type = item["type"]
            name = item["name"]
            

            parts = path.strip("/").split("/")
            path_parts = [p.split(":")[1] for p in parts if "field" not in p and "attribute" not in p]
            last_part = parts[-1]
            name = last_part.split(":")[1]

            # Check if path includes dynamic NXevent_data_em (per image)
            is_event_group = any("NXevent_data_em" in p for p in path_parts)

            if not is_event_group:
                
                value = insert_metadati(metadata_path, metadati)
                if isinstance(value,str):
                            if value.startswith("§e"):                            
                                value = eval(value.removeprefix("§e"))  # Rimuovi il prefisso §e
                            elif value.startswith("§l"):
                                value = f[value.removeprefix("§l")]  
                grp = get_or_create_group(f, path_parts)
                #print(f"[STATIC] Path: {path_parts}, Group: {grp.name}")

                if "field" in last_part:
                    if name not in grp:
                        #print(f"Creating dataset {name} in group {grp.name}")
                        if value is not None:
                            grp.create_dataset(name, data=value)                        
                elif "attribute" in last_part:
                    grp.attrs[name] = value

            else:
                for idx, image_path in enumerate(tiff_path):
                     metadati= metadata_extractor_tiff(image_path)                    
                     with tifffile.TiffFile(image_path) as tif:
                        image = tif.asarray()                        
                        value = insert_metadati(metadata_path, metadati)
                        if isinstance(value,str):
                            if value.startswith("§e"):                            
                                value = eval(value.removeprefix("§e"))  # Rimuovi il prefisso §e
                            elif value.startswith("§l"):
                                value = f[value.removeprefix("§l")]
                    # Replace NXevent_data_em with indexed version NXevent_data_em{idx}
                        new_parts = [
                            p.replace("NXevent_data_em", f"NXevent_data_em{idx}") if "NXevent_data_em" in p else p
                            for p in path_parts
                        ]
                        grp = get_or_create_group(f, new_parts)
                        #print(f"[IMG {idx}] Path: {new_parts}, Group: {grp.name}, value: {value}")

                        if "field" in last_part:
                            if name not in grp:
                                grp.create_dataset(name, data=value)
                        elif "attribute" in last_part:
                            grp.attrs[name] = value

    print(f"File NeXus created: {unique_filename}")
    return unique_filename




#  experiment_fields = {
#                 "experiment_name": "experiment_name",
#                 "operator_name": "operator_name",
#                 "description": "description",
#             }

# images_paths=[r"Au_np_2ev_00.tif",r"Au_np_2ev_01.tif",r"Au_np_2ev_02.tif"]
# output_path=".\tmp"
# dati_path=r"dati.txt"
# schema_json_path=r"NXem_def.nxdl.json"
# unique_filename=build_nexus_from_tiff_TEM_ED(tiff_path=images_paths, mapping_json_path=schema_json_path, out_nxs=output_path,extra_fields=experiment_fields):