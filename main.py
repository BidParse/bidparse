import os
import io
import json
import pandas as pd
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

app = FastAPI(title="BidParse API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

@app.get("/")
async def serve_home():
    return FileResponse("index.html")

@app.post("/api/parse")
async def parse_documents(files: List[UploadFile] = File(...)):
    all_rows = []

    prompt = """
    You are an expert data parsing assistant.
    Analyze all the text, tables, graphs, or line items shown in this document.
    Extract every single identifiable item or row.
    Return ONLY a valid JSON array of objects with the exact keys:
    "sku", "description", "qty", "unit", "unit_price", "total_price"
    If the document is non-financial or academic, map the fields logically.
    """

    for file in files:
        contents = await file.read()
        if len(contents) == 0:
            continue

        try:
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=[
                    types.Part.from_bytes(
                        data=contents,
                        mime_type="application/pdf"
                    ),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            data = json.loads(response.text)
            
            # Tag each row with the source filename
            for item in data:
                item["source_file"] = file.filename
                all_rows.append(item)
                
        except Exception as e:
            print(f"Error on {file.filename}: {e}")

    if not all_rows:
        raise HTTPException(status_code=500, detail="Failed to extract line items from the provided files.")

    # Build master DataFrame
    df = pd.DataFrame(all_rows)
    
    # Put source_file as the first column for clarity
    cols = ["source_file"] + [c for c in df.columns if c != "source_file"]
    df = df[cols]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Master_Extracted_Data")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=master_bids_extracted.xlsx"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)