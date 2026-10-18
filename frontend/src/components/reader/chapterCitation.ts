/** Evidence without a server-verified immutable chapter identity remains visible,
 * but must never navigate to whichever chapter now occupies its old number. */
export function chapterCitationHref(readerBase:string,citation:{chapter:number;block_id:string;chapter_key?:string|null}):string|null {
 if(!Number.isInteger(citation.chapter)||!citation.chapter_key||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(citation.chapter_key))return null;
 return `${readerBase}/${citation.chapter}?block=${encodeURIComponent(citation.block_id)}&chapter_key=${encodeURIComponent(citation.chapter_key)}`;
}
