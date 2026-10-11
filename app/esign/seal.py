"""Cryptographic sealing of the completed PDF (PAdES-style signature via pyHanko, MIT).

The seal proves the document has not been altered since all parties signed. It is a *platform* seal,
not each signer's personal signature; in production load a certificate issued to your organisation
(`FINTECH_SIGNING_P12_PATH`). Without one, an ephemeral self-signed identity is generated (dev only:
signatures from it are intact but not trusted by PDF readers).
"""
import datetime
import io
from functools import lru_cache

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from ..config import settings


def _ephemeral_p12() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FinTech Suite (development seal)")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"seal", key, cert, None, serialization.BestAvailableEncryption(b"dev"))


@lru_cache(maxsize=1)
def _signer() -> signers.SimpleSigner:
    if settings.signing_p12_path:
        return signers.SimpleSigner.load_pkcs12(settings.signing_p12_path, passphrase=settings.signing_p12_password.encode() or None)
    if settings.env == "production":
        raise RuntimeError("FINTECH_SIGNING_P12_PATH must be set in production to seal signed documents")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".p12") as f:
        f.write(_ephemeral_p12())
        f.flush()
        return signers.SimpleSigner.load_pkcs12(f.name, passphrase=b"dev")


def clear_cache() -> None:
    _signer.cache_clear()


def seal(pdf: bytes, reason: str = "All parties have signed") -> bytes:
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
    meta = signers.PdfSignatureMetadata(field_name="PlatformSeal", reason=reason, location="FinTech Suite")
    return signers.sign_pdf(writer, meta, signer=_signer()).getvalue()


def verify(pdf: bytes) -> dict:
    """Integrity check of the seal: {sealed, intact, valid}. `trusted` is deliberately not claimed."""
    reader = PdfFileReader(io.BytesIO(pdf))
    sigs = reader.embedded_signatures
    if not sigs:
        return {"sealed": False, "intact": False, "valid": False}
    # Trust only our own seal certificate: "trusted" then means "sealed by this platform's key", nothing more.
    ctx = ValidationContext(trust_roots=[_signer().signing_cert], allow_fetching=False)
    st = validate_pdf_signature(sigs[-1], signer_validation_context=ctx)
    return {"sealed": True, "intact": bool(st.intact), "valid": bool(st.valid), "platform_trusted": bool(st.trusted)}
