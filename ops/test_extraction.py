import sys
import os
import unittest
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd()))

from src.backend.ingest.dou_processor import DouProcessor

class TestDouProcessor(unittest.TestCase):
    def setUp(self):
        self.processor = DouProcessor()
        self.mock_xml = """<?xml version="1.0" encoding="utf-8"?>
<xml>
<article pubName="DO1" pubDate="04/01/2002" artType="DECRETO" artCategory="Atos do Poder Executivo/Presidência da República" numberPage="1">
    <body>
        <Identifica>DECRETO Nº 4.071</Identifica>
        <Ementa>Dispõe sobre...</Ementa>
        <Texto>
            &lt;p class='identifica'&gt;DECRETO Nº 4.071&lt;/p&gt;
            &lt;p&gt;O PRESIDENTE DA REPÚBLICA, no uso da atribuição que lhe confere o art. 84, inciso IV, da Constituição, e tendo em vista o disposto no Decreto nº 3.035, de 27 de abril de 1999.&lt;/p&gt;
            &lt;p&gt;Considerando a Lei nº 8.112 e a Medida Provisória nº 2.216-37.&lt;/p&gt;
            &lt;p&gt;Envolve a Casa Civil da Presidência da República e o Ministério da Fazenda.&lt;/p&gt;
            &lt;p class='assina'&gt;FERNANDO HENRIQUE CARDOSO&lt;/p&gt;
            &lt;p class='cargo'&gt;Presidente da República&lt;/p&gt;
            &lt;p&gt;Brasília, 3 de janeiro de 2002; 181º da Independência e 114º da República.&lt;/p&gt;
        </Texto>
        <Data></Data>
    </body>
</article>
</xml>
""".encode('utf-8')

    def test_extraction(self):
        doc = self.processor.process_xml(self.mock_xml, "test.xml", "test.zip")
        self.assertIsNotNone(doc)
        
        # 1. Deterministic ID
        # Should be date_section_hash
        self.assertTrue(doc.id.startswith("2002-01-04_DO1_"))
        
        # 2. Source Type
        self.assertEqual(doc.source_type, "liferay")
        
        # 3. References
        print(f"References: {doc.references}")
        targets = [ref.target for ref in doc.references]
        self.assertIn("Decreto 3.035", targets)
        self.assertIn("Lei 8.112", targets)
        self.assertIn("Medida Provisória 2.216-37", targets)
        
        # 4. Entities
        print(f"Entities: {doc.affected_entities}")
        self.assertIn("Casa Civil", doc.affected_entities)
        self.assertIn("Ministério da Fazenda", doc.affected_entities)
        
        # 5. Orgao/Category Swap
        self.assertEqual(doc.orgao, "Presidência da República")
        
        # 6. Signer
        print(f"Signer: {doc.structured.signer}")
        self.assertEqual(doc.structured.signer, "FERNANDO HENRIQUE CARDOSO")
        
        # 7. HTML Unescape
        print(f"Texto: {doc.texto[:100]}...")
        self.assertNotIn("&lt;", doc.texto)
        
        # 8. Data Text Fallback
        print(f"Data Text: {doc.data_text}")
        self.assertIn("3 de janeiro de 2002", doc.data_text)
        
        # 9. Enrichment
        self.assertEqual(doc.enrichment.relevance_score, 0.9)
        self.assertEqual(doc.enrichment.category, "Legislação Principal")
        
        # 10. Act Number
        self.assertEqual(doc.structured.act_number, "4.071")
        self.assertEqual(doc.structured.act_year, 2002)
        
        # Version
        self.assertEqual(doc.metadata.processing_version, "v2.2")

if __name__ == '__main__':
    unittest.main()
