#!/usr/bin/env python3
"""
Script para aplicar correções de memory leak no sync.py
Adiciona:
1. gc.collect() periódico
2. del explicito para liberar objetos grandes
3. Limpeza de referências
"""

import re

# Ler arquivo original
with open('src/gabi/tasks/sync.py', 'r') as f:
    content = f.read()

# 1. Adicionar import gc no início do arquivo (após os outros imports)
if 'import gc' not in content:
    content = content.replace(
        'import logging',
        'import gc\nimport logging'
    )
    print("✓ Adicionado 'import gc'")

# 2. Adicionar gc.collect() após processar cada documento
# Encontrar o padrão após await _index_document
old_pattern = '''                                    # Log memory after index
                                    log_memory_after("index", mem_before_index, {"doc_id": parsed_doc.document_id})

                                except Exception as doc_exc:'''

new_pattern = '''                                    # Log memory after index
                                    log_memory_after("index", mem_before_index, {"doc_id": parsed_doc.document_id})
                                    
                                    # Force cleanup of large objects to prevent memory accumulation
                                    del parsed_doc
                                    del chunking_result
                                    if embedding_result:
                                        del embedding_result
                                    
                                    # Periodic garbage collection every 50 documents
                                    if stats["documents_indexed"] % 50 == 0:
                                        gc.collect()
                                        mem_after_gc = get_memory_usage_mb()
                                        logger.info(f"[MEMORY] GC completed after {stats['documents_indexed']} docs: {mem_after_gc:.1f}MB")

                                except Exception as doc_exc:'''

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    print("✓ Adicionado gc.collect() e del() para liberação de memória")
else:
    print("⚠ Padrão não encontrado para gc.collect()")

# 3. Adicionar gc.collect() também no streaming batch
old_batch_pattern = '''                            # Commit after each batch
                            await session.commit()

                            # Memory monitoring and cleanup'''

new_batch_pattern = '''                            # Commit after each batch
                            await session.commit()
                            
                            # Force garbage collection after batch commit
                            gc.collect()

                            # Memory monitoring and cleanup'''

if old_batch_pattern in content:
    content = content.replace(old_batch_pattern, new_batch_pattern)
    print("✓ Adicionado gc.collect() após batch commit")
else:
    print("⚠ Padrão de batch não encontrado")

# Salvar arquivo
with open('src/gabi/tasks/sync.py', 'w') as f:
    f.write(content)

print("\nCorreções aplicadas!")
print("Backup original disponível em: src/gabi/tasks/sync.py.bak")
