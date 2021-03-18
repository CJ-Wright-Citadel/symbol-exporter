"""
Perform a reverse index of the symbols, creating the symbol table that maps symbols to the artifacts
that provide them from AST derived symbols.
"""

"""
BSD 3-Clause License

Copyright (c) 2018, Re(search) Gro(up)
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
from concurrent.futures._base import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from itertools import groupby
from random import shuffle

from tqdm import tqdm

from symbol_exporter.ast_symbol_extractor import version
from symbol_exporter.db_access_model import WebDB


def inner_loop(artifact_name):
    web_interface = WebDB()
    symbols = web_interface.get_artifact_symbols(artifact_name)
    all_symbol_tables = {}
    for top_level_name, keys in groupby(
        sorted(symbols), lambda x: x.partition(".")[0].lower()
    ):
        print(top_level_name)
        # carve out for star imports which don't have dots
        if top_level_name == "*":
            continue
        # download the existing symbol table
        symbol_table_with_metadata = web_interface.get_symbol_table(top_level_name)
        symbol_table = symbol_table_with_metadata.get("symbol table", {})
        metadata = symbol_table_with_metadata.get("metadata", {})
        # update the symbol table
        for k in list(symbols):
            symbol_table.setdefault(k, []).append(artifact_name)
        # add artifacts to metadata
        metadata["version"] = version
        metadata.setdefault("indexed artifacts", []).append(artifact_name)
        # push back to server
        web_interface.push_symbol_table(
            top_level_name, {"symbol table": symbol_table, "metadata": metadata}
        )
        all_symbol_tables[top_level_name] = symbol_table
    return all_symbol_tables


if __name__ == "__main__":
    web_interface = WebDB()
    extracted_artifacts = web_interface.get_current_symbol_table_artifacts()
    all_artifacts = web_interface.get_current_extracted_pkgs().values()

    artifacts_to_index = list(set(all_artifacts) - set(extracted_artifacts))
    print(f"Number of artifacts to index: {len(artifacts_to_index)}")

    # The shuffle here is to try to not have two threads running on the same symbol table json at once if possible
    shuffle(artifacts_to_index)
    pool = ThreadPoolExecutor()
    # Note that this is a race condition here, two threads could try to write to the same symbol table
    # however one of those will win so next round there will be one added safely and this continues
    # until none are left to be added
    print("issuing futures")
    futures = {
        pool.submit(inner_loop, artifact_name): artifact_name
        for artifact_name in tqdm(artifacts_to_index[:10000])
    }
    print("awaiting futures")
    for future in tqdm(as_completed(futures), total=len(futures)):
        print(futures[future])
        try:
            future.result()
        except Exception as e:
            print(e)
    pool.shutdown()
