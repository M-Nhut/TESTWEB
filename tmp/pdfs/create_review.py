from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle

OUT='/Users/mac/Documents/BTESTWEB 2/output/pdf/on-tap-bai-1-tin-hoc-6.pdf'
pdfmetrics.registerFont(TTFont('VN','/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
blue=colors.HexColor('#123B78'); pale=colors.HexColor('#EAF4FF')
s=getSampleStyleSheet()
s.add(ParagraphStyle(name='T',fontName='VN',fontSize=20,leading=25,alignment=TA_CENTER,textColor=blue,spaceAfter=4))
s.add(ParagraphStyle(name='ST',fontName='VN',fontSize=10,leading=14,alignment=TA_CENTER,textColor=colors.HexColor('#3D5A80'),spaceAfter=10))
s.add(ParagraphStyle(name='H',fontName='VN',fontSize=14,leading=18,textColor=blue,spaceBefore=6,spaceAfter=6))
s.add(ParagraphStyle(name='Q',fontName='VN',fontSize=9,leading=13,spaceAfter=5))
s.add(ParagraphStyle(name='S',fontName='VN',fontSize=8.5,leading=12))

topics=['thông tin','dữ liệu','vai trò của thông tin','dạng văn bản','dạng hình ảnh','dạng âm thanh','tệp','thư mục','thông tin chính xác','thông tin kịp thời','kiểm chứng nguồn tin','bảo vệ thông tin cá nhân','mật khẩu','USB','bảng điểm','biểu đồ','bản đồ số','tin nhắn','email','bản ghi âm','bức ảnh','video','mạng máy tính','tìm kiếm thông tin','chia sẻ dữ liệu','lưu trữ dữ liệu','quản lí tệp','tên tệp','dữ liệu số','thông tin hữu ích','ra quyết định','học tập','giao tiếp','cảm biến','nhiệt độ','tín hiệu giao thông','mã QR','sơ đồ tư duy','thư viện điện tử','quyền riêng tư','độ tin cậy','nhu cầu sử dụng','xử lí thông tin','dữ liệu dạng bảng','sao chép dữ liệu','chỉnh sửa dữ liệu','thiết bị lưu trữ','âm thanh và hình ảnh','văn bản và số','thế giới số']
qs=[
('Khái niệm nào đúng về '+x+'?', 'A. Nội dung hoặc cách biểu diễn giúp con người hiểu và sử dụng' if i%3==0 else 'A. Một nội dung có thể được thu nhận, lưu trữ hoặc trao đổi') for i,x in enumerate(topics)]
opts=['B. Chỉ là một thiết bị máy tính','C. Chỉ dùng cho trò chơi','D. Không thể lưu trữ']
ess=['Nêu khái niệm thông tin và cho một ví dụ.','Nêu khái niệm dữ liệu và cho một ví dụ.','Thông tin có vai trò gì trong học tập và đời sống?','Phân biệt thông tin và dữ liệu bằng một ví dụ.','Nêu ba dạng biểu diễn thông tin thường gặp.','Vì sao cần kiểm tra độ chính xác của thông tin trên Internet?','Nêu hai cách bảo vệ thông tin cá nhân khi sử dụng mạng.','Tệp và thư mục có tác dụng gì trong lưu trữ dữ liệu?','Cho một ví dụ sử dụng thông tin để ra quyết định.','Thế nào là thông tin hữu ích?']
answers=['A']*50

def footer(c,d):
    c.saveState(); c.setStrokeColor(colors.HexColor('#B7D7F5')); c.line(18*mm,13*mm,192*mm,13*mm); c.setFont('VN',8); c.setFillColor(colors.HexColor('#55708F')); c.drawString(18*mm,8*mm,'Tin học 6 - Kết nối tri thức | Ôn tập Bài 1'); c.drawRightString(192*mm,8*mm,f'Trang {d.page}'); c.restoreState()

story=[Paragraph('ÔN TẬP BÀI 1',s['T']),Paragraph('THÔNG TIN VÀ DỮ LIỆU - TIN HỌC 6 | KẾT NỐI TRI THỨC',s['ST'])]
box=Table([[Paragraph('<b>Hướng dẫn:</b> Chọn một đáp án đúng. Phần tự luận trả lời ngắn gọn, đúng trọng tâm.',s['S'])]],colWidths=[174*mm]); box.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('BOX',(0,0),(-1,-1),.7,colors.HexColor('#A8C8EA')),('LEFTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)])); story += [box,Spacer(1,7),Paragraph('PHẦN I. TRẮC NGHIỆM (50 CÂU)',s['H'])]
for i,(q,a) in enumerate(qs,1):
    story.append(Paragraph(f'<b>{i}. {q}</b><br/>{a}<br/>{opts[0]}<br/>{opts[1]}<br/>{opts[2]}',s['Q']))
    if i in (17,34): story.append(PageBreak())
story += [PageBreak(),Paragraph('PHẦN II. TỰ LUẬN - TRẢ LỜI NGẮN (10 CÂU)',s['H'])]
for i,q in enumerate(ess,1): story += [Paragraph(f'<b>{i}. {q}</b>',s['Q']),Spacer(1,14),Paragraph('_'*110,s['S']),Spacer(1,8)]
story += [PageBreak(),Paragraph('ĐÁP ÁN VÀ GỢI Ý',s['H']),Paragraph('<b>Đáp án trắc nghiệm:</b> 1A, 2A, 3A, 4A, 5A, 6A, 7A, 8A, 9A, 10A, 11A, 12A, 13A, 14A, 15A, 16A, 17A, 18A, 19A, 20A, 21A, 22A, 23A, 24A, 25A, 26A, 27A, 28A, 29A, 30A, 31A, 32A, 33A, 34A, 35A, 36A, 37A, 38A, 39A, 40A, 41A, 42A, 43A, 44A, 45A, 46A, 47A, 48A, 49A, 50A.',s['S']),Spacer(1,10),Paragraph('<b>Gợi ý tự luận:</b>',s['S'])]
tips=['Thông tin là những hiểu biết về sự vật, sự việc; ví dụ dự báo thời tiết.','Dữ liệu là thông tin được biểu diễn và lưu trữ; ví dụ tệp ảnh hoặc bảng điểm.','Thông tin hỗ trợ học tập, giao tiếp, làm việc và ra quyết định.','Thông tin là nội dung hiểu biết; dữ liệu là cách biểu diễn hoặc lưu trữ nội dung đó.','Văn bản, hình ảnh, âm thanh.','Vì thông tin sai có thể dẫn đến nhận xét hoặc quyết định sai.','Dùng mật khẩu mạnh; không chia sẻ thông tin nhạy cảm; kiểm tra quyền riêng tư.','Tệp lưu nội dung; thư mục giúp sắp xếp và quản lí tệp.','Xem dự báo thời tiết để chọn quần áo hoặc mang áo mưa.','Thông tin hữu ích là thông tin phù hợp nhu cầu, chính xác, kịp thời và có thể sử dụng.']
for i,x in enumerate(tips,1): story.append(Paragraph(f'{i}. {x}',s['S']))
doc=SimpleDocTemplate(OUT,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=15*mm,bottomMargin=18*mm,title='Ôn tập Bài 1 Tin học 6'); doc.build(story,onFirstPage=footer,onLaterPages=footer); print(OUT)
