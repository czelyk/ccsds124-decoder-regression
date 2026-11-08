# T1 karşı örneğinin bağımsız tekrar yürütülmesi

13 Ekim 2026. verify_counterexample.py ayrı küçük C wrapper ve ELF üretir; araştırmacı ajanının ELF'sini veya encoder çıktısı üretme kodunu çalıştırmaz. Girdi üç sabit wire dizisidir. İlk kayıt 13 sıfır byte, sonraki iki kayıt 01 + 12 sıfır byte beklenir. Kayıpsız kontrol, üç kaydın tamamını rc=0 ve doğru içerikle çözer. İkinci kayıt silindiğinde receiver notify_packet_loss(1) çağırır; üçüncü kayıt rc=0/status=0 dönmesine rağmen sıfır içerik verir.

-O0/-O2 ve max-packet 104/2048 bit çaprazında dört bağımsız build bu davranışı aynı biçimde yeniden üretti. Her build'de byte-aligned padding ve gerçek valid bit uzunlukları 126/20/8 ayrı yürütüldü; sekiz reception configuration'ın hepsinde kayıpsız kontrol ve karşı örnek aynı sonucu verdi. Padding farkı davranışı açıklamadı. Sonuç: results.json. Girdi/original oracle C DUT'a verilmez; offline karşılaştırılır. Her ELF ve üç vendor kaynak dosyası SHA256 kayıtlıdır. Vendor commit a049cfeec1900414be5b9fc0c18c49436cbb3c82, tanagraspace/ccsds124, MIT. Var olan vendor kaynakları değişmedi.

API anlamı include/ccsds124.h satır 980–996'da belirtilir: checked fonksiyon accuracy-guarantee değerlendirdiğini ve OK'nin guaranteed olduğunu söyler. notify_packet_loss API'si tam kayıp sayısının receiver'da bilindiğini varsayar; burada doğru biliniyor. decompress.c 825–854 non-reference kararında Vt=0 için varsayılan guaranteed=1 kalır; kayıpta mask_synced sıfırlanmış olması bu dalda kontrol edilmiyor. Daha büyük burst sonucunu tek bu dala indirgemiyoruz; başka source branch etkileri olabilir.

[Birincil standart](https://ccsds.org/Pubs/124x0b1.pdf), §2.1'de yeniden edinim için mask/data durumunu açıklar; §3.3.2 ilk R+1 input için ft/rt kurallarını koyar. Bu örnek R0 ve ilk input ft=rt=1 içerir. Standart encoder ve wire biçimini tanımlar; checked API'nin karar ağacı standardın birebir zorunlu decoder tasarımı diye sunulmayacak. Güçlü ileri/partial/backward receiver yakın öncülleri ayrıca karşılaştırılmalı.

Bu fiziksel STM32 testi, WCET veya radyasyon ölçümü değildir. Emulator CPU'yu ve C fonksiyonunu yürütür, çevre birimi/RF/enerji modellemez. Kayıpsız kontrol ve API kaynak okuması confound'ları azaltır; tam bağımsız CCSDS bitstream conformance suite yoktur. Bunlar bug'ın küresel standarda, bütün kütüphane sürümlerine veya uçuş görevlerine genellenmesini sağlamaz.

Son sert eleştiri:
- Tek az kullanılan açık kaynak vendor bug'ı tek başına kapsamlı IAC çalışması olmayabilir. Katkı, geçerli teşhis alanlarının güvenilirliği için aktarılabilir test sözleşmesi ve güçlü receiver karşılaştırmasıyla desteklenmeli.
- Güçlü standards-aware receiver aynı hatayı önlüyorsa “yeni decompression algoritması” iddiası elenir; validation/configuration seçimi sorusu kalabilir.
- Başarı sadece packets decoded veya encoder ratio ile tanımlanırsa yanlış teşhis bilgisini faydalı çıktı sayma riski vardır. False-guaranteed field kritik ölçüt olmalı.
- Tek elverişli loss schedule'a güvenmek yeterli değil; kayıpsız, uzun kayıp, startup kaybı, ref/mask periyotları, yanlış yapılandırma dışlaması ve yeniden edinim testleri gerekir.
- Nihai konu kararı henüz verilmedi. Bu çıktı T1'de karar değiştiren somut ön kanıttır; IAC kabul veya uçuş uygunluğu kanıtı değildir.

