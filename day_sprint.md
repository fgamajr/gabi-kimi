
› ok, now that everything seems to be working (discovering, ingesting, processing, indexing, embedding), I need a panel control to monitor everything and to start/restart and stop any phase by the pressing of a buttom. So I
  developed a frontend in Lovable that is gitted clone on this computer on /home/fgamajr/dev/user-first-view. So the first task of the day is to create or recreate the entire api to match the frontend requriments. The second task
  is to connect the frontend and the api. And yet, the third task of the day is a simpler one. Delete all mcps we may have and create a new based on elastic indexed we might have and the embeddings. So we have exact match using
  elastic by normas, acórdãos, publicações, leis, etc and a hybrid approach to get the semantic meanings. That's not all. Embeddings approach require a bunch of new technologies to work properly, I mean beyond the basics: 1) 1.
  Cross-Encoder Reranking (highest impact, easiest to add); 2) 2. Vision-Language Models for Document Understanding (replaces pdfplumber + OCR); 3) 3. GraphRAG (biggest long-term payoff); 4) 4. Learned Sparse Embeddings (SPLADE).
  They are all well explained here: /home/fgamajr/dev/gabi-kimi/vision.md. And yet we plan now moving to production fly.io instances, so I ask you upfront: do we "rag" here and then upload or we move all to fly.io just now? This
  would be task 4 of the day.