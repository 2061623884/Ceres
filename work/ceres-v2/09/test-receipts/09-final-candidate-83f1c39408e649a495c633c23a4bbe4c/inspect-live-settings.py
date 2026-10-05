import json
from app.core.config import get_settings
s=get_settings()
print(json.dumps({'llm_mode':s.llm_mode,'llm_model':s.llm_model,'memory_model':s.memory_model,'business_data_mode':s.business_data_mode,'retrieval_mode':s.retrieval_mode,'retrieval_index_configured':bool(s.retrieval_index_dir),'embedding_model':s.embedding_model,'embedding_dimension':s.embedding_dimension,'llm_timeout':s.llm_timeout,'llm_credential_present':bool(s.openai_api_key),'embedding_credential_present':bool(s.embedding_api_key)},ensure_ascii=False))
